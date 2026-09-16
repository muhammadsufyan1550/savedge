from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.downloader import process_export_zip
from app.session import session_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("savedge.app")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Savedge",
    description="Bulk-download Instagram saved posts from official export ZIP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB


def delayed_cleanup(session_id: str, delay_seconds: int = 120):
    """Run delayed cleanup in a background thread to allow download to finish."""
    def _runner():
        time.sleep(delay_seconds)
        session_manager.cleanup_session(session_id)

    threading.Thread(target=_runner, daemon=True).start()


def run_download_worker(session_id: str, zip_path: Path, session_dir: Path):
    """Background worker thread executing the downloader workflow."""
    logger.info("Starting background worker for session %s", session_id)
    try:
        session_manager.update_session(
            session_id,
            state="extracting",
            status_message="Extracting Instagram ZIP export...",
        )

        def on_extract():
            session_manager.update_session(
                session_id,
                state="extracting",
                status_message="Searching for saved posts JSON in export...",
            )

        def on_progress(current: int, total: int, failed: int, url: str):
            session_manager.update_session(
                session_id,
                state="downloading",
                current=current,
                total=total,
                failed=failed,
                current_url=url,
                status_message=f"Downloading post {current} of {total}...",
            )

        def on_packaging():
            session_manager.update_session(
                session_id,
                state="packaging",
                status_message="Packaging downloaded media into final ZIP archive...",
            )

        output_zip, success_count, failed_count = process_export_zip(
            session_id=session_id,
            zip_path=zip_path,
            session_dir=session_dir,
            on_extract=on_extract,
            on_progress=on_progress,
            on_packaging=on_packaging,
            is_cancelled=lambda: session_manager.is_cancelled(session_id),
            register_process=lambda proc: session_manager.set_process(session_id, proc),
        )

        msg = f"Done! Successfully downloaded {success_count} posts"
        if failed_count > 0:
            msg += f" ({failed_count} failed - listed in failed_urls.txt in the zip)."
        else:
            msg += "."

        session_manager.update_session(
            session_id,
            state="done",
            output_zip=output_zip,
            status_message=msg,
        )
        logger.info("Session %s completed successfully (%d downloaded, %d failed)", session_id, success_count, failed_count)

    except InterruptedError:
        logger.info("Worker for session %s terminated cleanly due to user cancellation.", session_id)
        session_manager.cleanup_session(session_id)
        return
    except Exception as exc:
        logger.exception("Error in worker for session %s: %s", session_id, exc)
        session_manager.update_session(
            session_id,
            state="error",
            error_msg=str(exc),
            status_message=f"Error: {exc}",
        )



@app.get("/healthz")
@app.get("/health")
def health_check():
    """Healthcheck endpoint for Render.com monitoring."""
    return {"status": "ok", "service": "savedge"}


@app.post("/upload")
async def upload_export(file: UploadFile = File(...)):
    """Accepts Instagram export ZIP, saves to session folder, starts worker thread."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Please upload an official Instagram export .zip file.",
        )

    session_id = str(uuid.uuid4())
    session = session_manager.create_session(session_id)
    if not session.session_dir:
        raise HTTPException(status_code=500, detail="Failed to initialize session directory.")

    zip_path = session.session_dir / "upload.zip"

    uploaded_bytes = 0
    try:
        with open(zip_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                uploaded_bytes += len(chunk)
                if uploaded_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Uploaded file exceeds maximum limit of 500 MB.",
                    )
                buffer.write(chunk)
    except HTTPException:
        session_manager.cleanup_session(session_id)
        raise
    except Exception as e:
        session_manager.cleanup_session(session_id)
        logger.exception("Failed to write uploaded file for %s", session_id)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # Launch processing in a dedicated background thread
    worker = threading.Thread(
        target=run_download_worker,
        args=(session_id, zip_path, session.session_dir),
        daemon=True,
        name=f"Worker-{session_id[:8]}",
    )
    worker.start()

    return {
        "session_id": session_id,
        "status": "processing",
        "filename": file.filename,
    }


@app.get("/progress/{session_id}")
async def progress_stream(session_id: str):
    """Server-Sent Events (SSE) stream emitting real-time download progress."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    async def event_generator():
        last_state = None
        last_current = -1
        last_ping = time.time()

        while True:
            sess = session_manager.get_session(session_id)
            if not sess:
                yield f"data: {json.dumps({'state': 'error', 'error_msg': 'Session expired'})}\n\n"
                break

            current_state = sess.state
            current_count = sess.current
            now = time.time()

            # Push state if state changed, progress incremented, or 2s heartbeat interval elapsed
            if current_state != last_state or current_count != last_current or (now - last_ping >= 2.0):
                payload = sess.to_dict()
                yield f"data: {json.dumps(payload)}\n\n"
                last_state = current_state
                last_current = current_count
                last_ping = now

            if current_state in ("done", "error", "cancelled"):
                await asyncio.sleep(0.5)
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/cancel/{session_id}")
def cancel_session(session_id: str):
    """Cancels an active download session and immediately deletes all server temp files."""
    success = session_manager.cancel_session(session_id)
    return {"status": "cancelled", "session_id": session_id, "success": success}


@app.get("/status/{session_id}")
def get_session_status(session_id: str):
    """Lightweight polling endpoint as a fallback for SSE."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    return session.to_dict()


@app.get("/download/{session_id}")
def download_archive(session_id: str, background_tasks: BackgroundTasks):
    """Download the final packaged ZIP file containing downloaded media."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    if session.state != "done" or not session.output_zip or not session.output_zip.exists():
        raise HTTPException(
            status_code=400,
            detail="The download ZIP archive is not ready yet or is unavailable.",
        )

    # Schedule cleanup after 2 minutes so multiple chunks or download retries don't fail
    background_tasks.add_task(delayed_cleanup, session_id, 120)

    return FileResponse(
        path=str(session.output_zip),
        filename=f"savedge_{session_id[:8]}.zip",
        media_type="application/zip",
    )


# Serve index.html directly at root
@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend file not found.")
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


# Mount static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
