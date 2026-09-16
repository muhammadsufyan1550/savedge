from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

logger = logging.getLogger("savedge.session")

SessionState = Literal[
    "uploading",
    "extracting",
    "downloading",
    "packaging",
    "done",
    "error",
    "cancelled",
]


@dataclass
class Session:
    session_id: str
    state: SessionState = "uploading"
    total: int = 0
    current: int = 0
    failed: int = 0
    current_url: str = ""
    status_message: str = "Uploading..."
    output_zip: Optional[Path] = None
    session_dir: Optional[Path] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    error_msg: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    current_process: Optional[object] = None


    def to_dict(self) -> dict:
        percent = 0.0
        if self.total > 0:
            percent = round((self.current / self.total) * 100, 1)
        elif self.state == "done":
            percent = 100.0

        return {
            "session_id": self.session_id,
            "state": self.state,
            "total": self.total,
            "current": self.current,
            "failed": self.failed,
            "current_url": self.current_url,
            "status_message": self.status_message,
            "percent": percent,
            "has_download": bool(self.output_zip and self.output_zip.exists()),
            "created_at": self.created_at,
            "error_msg": self.error_msg,
        }


class SessionManager:
    """Thread-safe manager for Savedge download sessions."""

    def __init__(self, base_temp_dir: Optional[Path] = None, max_age_seconds: int = 1800):
        self._lock = threading.Lock()
        self._sessions: Dict[str, Session] = {}
        self.base_temp_dir = base_temp_dir or (Path(tempfile.gettempdir()) / "savedge")
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_seconds
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._start_cleanup_worker()

    def create_session(self, session_id: str) -> Session:
        with self._lock:
            session_dir = self.base_temp_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            session = Session(
                session_id=session_id,
                session_dir=session_dir,
                created_at=time.time(),
                last_activity=time.time(),
            )
            self._sessions[session_id] = session
            logger.info("Created session %s at %s", session_id, session_dir)
            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def update_session(self, session_id: str, **kwargs) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            session.last_activity = time.time()
            return session

    def cancel_session(self, session_id: str) -> bool:
        """Signals session cancellation, terminates active subprocess, and purges temp storage."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.state = "cancelled"
            session.cancel_event.set()
            if session.current_process:
                try:
                    session.current_process.terminate()
                except Exception as e:
                    logger.debug("Error terminating process for %s: %s", session_id, e)

        return self.cleanup_session(session_id)

    def is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return bool(session and session.cancel_event.is_set())

    def set_process(self, session_id: str, process: Optional[object]):
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.current_process = process
                if process and session.cancel_event.is_set():
                    try:
                        process.terminate()
                    except Exception:
                        pass

    def cleanup_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session and session.session_dir and session.session_dir.exists():
            try:
                shutil.rmtree(session.session_dir, ignore_errors=True)
                logger.info("Cleaned up session directory for %s", session_id)
                return True
            except Exception as e:
                logger.warning("Error deleting directory for %s: %s", session_id, e)
        return False

    def cleanup_expired(self) -> int:
        now = time.time()
        expired_ids: list[str] = []
        with self._lock:
            for s_id, session in self._sessions.items():
                if now - session.last_activity > self.max_age_seconds:
                    expired_ids.append(s_id)

        cleaned_count = 0
        for s_id in expired_ids:
            if self.cleanup_session(s_id):
                cleaned_count += 1

        # Also purge any orphaned directories in base_temp_dir older than max_age_seconds
        try:
            for item in self.base_temp_dir.iterdir():
                if item.is_dir():
                    try:
                        mtime = item.stat().st_mtime
                        if now - mtime > self.max_age_seconds:
                            shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Error checking base_temp_dir for expired dirs: %s", e)

        if cleaned_count > 0:
            logger.info("Cleaned up %d expired sessions", cleaned_count)
        return cleaned_count

    def _start_cleanup_worker(self):
        def worker():
            while not self._stop_event.wait(60):
                try:
                    self.cleanup_expired()
                except Exception as e:
                    logger.error("Error during session cleanup: %s", e)

        self._cleanup_thread = threading.Thread(target=worker, daemon=True, name="SessionCleanupWorker")
        self._cleanup_thread.start()

    def shutdown(self):
        self._stop_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)


session_manager = SessionManager()
