import time
from pathlib import Path
import pytest
from app.session import SessionManager


def test_session_creation_and_update(tmp_path: Path):
    manager = SessionManager(base_temp_dir=tmp_path, max_age_seconds=60)
    session = manager.create_session("test-123")
    assert session.session_id == "test-123"
    assert session.state == "uploading"
    assert session.session_dir.exists()

    manager.update_session("test-123", state="downloading", total=10, current=3)
    updated = manager.get_session("test-123")
    assert updated.state == "downloading"
    assert updated.current == 3
    assert updated.total == 10
    assert updated.to_dict()["percent"] == 30.0

    manager.shutdown()


def test_session_cleanup(tmp_path: Path):
    manager = SessionManager(base_temp_dir=tmp_path, max_age_seconds=1)
    session = manager.create_session("cleanup-test")
    session_dir = session.session_dir
    assert session_dir.exists()

    manager.cleanup_session("cleanup-test")
    assert not session_dir.exists()
    assert manager.get_session("cleanup-test") is None

    manager.shutdown()


def test_cleanup_expired(tmp_path: Path):
    manager = SessionManager(base_temp_dir=tmp_path, max_age_seconds=1)
    session = manager.create_session("expired-test")
    session.last_activity = time.time() - 10  # force expired

    cleaned = manager.cleanup_expired()
    assert cleaned >= 1
    assert manager.get_session("expired-test") is None

    manager.shutdown()
