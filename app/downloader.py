from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("savedge.downloader")


def find_saved_json(extract_dir: Path) -> Optional[Path]:
    """Search for Instagram saved posts/media JSON file in extracted export."""
    candidates = [
        "your_instagram_activity/saved/saved_posts.json",
        "saved/saved_posts.json",
        "saved_posts.json",
        "your_instagram_activity/saved/saved_media.json",
        "saved/saved_media.json",
        "saved_media.json",
    ]
    for rel in candidates:
        p = extract_dir / rel
        if p.exists():
            return p
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f in ("saved_posts.json", "saved_media.json"):
                return Path(root) / f
    return None


def extract_urls(json_path: Path) -> List[str]:
    """Parse Instagram saved posts/media JSON to extract valid post URLs."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    if isinstance(data, dict):
        items = data.get("saved_saved_media") or data.get("saved_media") or []
    elif isinstance(data, list):
        items = data

    urls: List[str] = []
    for item in items:
        try:
            href = None
            if isinstance(item.get("label_values"), list):
                for lv in item["label_values"]:
                    if lv.get("label") == "URL" and lv.get("href"):
                        href = lv["href"]
                        break
            if not href and isinstance(item.get("string_map_data"), dict):
                smd = item["string_map_data"]
                href = (
                    smd.get("Saved on", {}).get("href")
                    or smd.get("Href", {}).get("value")
                    or smd.get("href", {}).get("value")
                )
            if href and href.startswith("http"):
                urls.append(href)
        except (KeyError, TypeError):
            pass
    return urls


def get_ytdlp_cmd() -> Optional[List[str]]:
    """Locate yt-dlp executable or Python module."""
    candidates = [
        ["yt-dlp"],
        [sys.executable, "-m", "yt_dlp"],
    ]
    for cmd in candidates:
        try:
            subprocess.run(cmd + ["--version"], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def download_url(
    url: str,
    output_dir: Path,
    index: int,
    total: int,
    ytdlp_cmd: List[str],
    timeout_seconds: int = 120,
    is_cancelled: Optional[Callable[[], bool]] = None,
    register_process: Optional[Callable[[Optional[subprocess.Popen]], None]] = None,
) -> bool:
    """Download a single Instagram post/media URL using yt-dlp."""
    if is_cancelled and is_cancelled():
        return False

    logger.info("[%d/%d] Downloading: %s", index, total, url)
    cmd = ytdlp_cmd + [
        "--output",
        str(output_dir / "%(upload_date)s_%(id)s.%(ext)s"),
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--socket-timeout",
        "30",
        url,
    ]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if register_process:
            register_process(proc)

        start_time = time.time()
        while True:
            ret = proc.poll()
            if ret is not None:
                return ret == 0
            if is_cancelled and is_cancelled():
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return False
            if time.time() - start_time > timeout_seconds:
                proc.terminate()
                logger.warning("Timeout downloading URL [%d/%d]: %s", index, total, url)
                return False
            time.sleep(0.15)
    except Exception as e:
        logger.warning("Error running yt-dlp for %s: %s", url, e)
        return False
    finally:
        if register_process:
            register_process(None)


def process_export_zip(
    session_id: str,
    zip_path: Path,
    session_dir: Path,
    on_extract: Optional[Callable[[], None]] = None,
    on_progress: Optional[Callable[[int, int, int, str], None]] = None,
    on_packaging: Optional[Callable[[], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    register_process: Optional[Callable[[Optional[subprocess.Popen]], None]] = None,
) -> Tuple[Path, int, int]:
    """
    Extract export ZIP, find saved posts, download media via yt-dlp,
    and package results into a downloadable ZIP archive.

    Returns:
        (output_zip_path, success_count, failed_count)
    """
    if is_cancelled and is_cancelled():
        raise InterruptedError("Download was cancelled by user.")

    ytdlp_cmd = get_ytdlp_cmd()
    if not ytdlp_cmd:
        raise RuntimeError("yt-dlp is not available. Please verify yt-dlp is installed.")

    extract_dir = session_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    if on_extract:
        on_extract()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile:
        raise ValueError("The uploaded file is not a valid ZIP archive.")

    if is_cancelled and is_cancelled():
        raise InterruptedError("Download was cancelled by user.")

    json_path = find_saved_json(extract_dir)
    if not json_path:
        raise ValueError(
            "Could not find 'saved_posts.json' or 'saved_media.json' in the ZIP archive. "
            "Please ensure you exported 'Saved posts' from Instagram in JSON format."
        )

    urls = extract_urls(json_path)
    if not urls:
        raise ValueError("No saved post URLs found in the export JSON file.")

    total_urls = len(urls)
    media_dir = session_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    failed: List[str] = []

    try:
        for i, url in enumerate(urls, 1):
            if is_cancelled and is_cancelled():
                logger.info("Session %s was cancelled by user.", session_id)
                raise InterruptedError("Download was cancelled by user.")

            if on_progress:
                on_progress(i, total_urls, len(failed), url)

            ok = download_url(
                url,
                media_dir,
                i,
                total_urls,
                ytdlp_cmd,
                is_cancelled=is_cancelled,
                register_process=register_process,
            )

            if is_cancelled and is_cancelled():
                logger.info("Session %s was cancelled by user.", session_id)
                raise InterruptedError("Download was cancelled by user.")

            if ok:
                success += 1
            else:
                failed.append(url)

            if on_progress:
                on_progress(i, total_urls, len(failed), url)

        # If any failed, record failed URLs in a text file
        if failed:
            failed_log = media_dir / "failed_urls.txt"
            with open(failed_log, "w", encoding="utf-8") as f:
                f.write("# URLs that could not be downloaded\n")
                f.write("\n".join(failed))

        if is_cancelled and is_cancelled():
            raise InterruptedError("Download was cancelled by user.")

        if on_packaging:
            on_packaging()

        output_zip = session_dir / f"savedge_{session_id[:8]}.zip"
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
            for file_path in media_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(media_dir)
                    out_zf.write(file_path, arcname=arcname)

        # Disk space mitigation for free tier:
        # Safely remove raw extracted folder and media folder, leaving only the final ZIP
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
            shutil.rmtree(media_dir, ignore_errors=True)
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Error cleaning temporary subfolders for %s: %s", session_id, e)

        return output_zip, success, len(failed)

    finally:
        if is_cancelled and is_cancelled():
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
                shutil.rmtree(media_dir, ignore_errors=True)
                if zip_path.exists():
                    zip_path.unlink(missing_ok=True)
            except Exception:
                pass

