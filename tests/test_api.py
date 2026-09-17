import io
import json
import zipfile
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.session import session_manager

client = TestClient(app)


def test_health_check():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "Savedge" in response.text
    assert "buymeacoffee.com/savedge" in response.text
    assert "<title>Savedge</title>" in response.text
    assert 'name="description"' in response.text
    assert "savedge.onrender.com" in response.text
    assert 'property="og:title"' in response.text
    assert 'name="twitter:card"' in response.text
    assert "application/ld+json" in response.text
    assert "WebApplication" in response.text
    assert "Frequently Asked Questions" in response.text
    assert "How do I download my Instagram saved posts?" in response.text
    assert "Can I bulk download Instagram reels?" in response.text
    assert "Is Savedge free to use?" in response.text


def test_robots_txt():
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "User-agent: *" in response.text
    assert "Allow: /" in response.text
    assert "savedge.onrender.com/sitemap.xml" in response.text


def test_sitemap_xml():
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "savedge.onrender.com" in response.text
    assert "<urlset" in response.text


def test_upload_invalid_extension():
    response = client.post(
        "/upload",
        files={"file": ("test.txt", b"invalid data", "text/plain")}
    )
    assert response.status_code == 400
    assert "Invalid file format" in response.json()["detail"]


def test_status_not_found():
    response = client.get("/status/non-existent-uuid")
    assert response.status_code == 404


def test_download_not_ready():
    session = session_manager.create_session("not-ready-session")
    session_manager.update_session("not-ready-session", state="downloading")
    response = client.get("/download/not-ready-session")
    assert response.status_code == 400
    session_manager.cleanup_session("not-ready-session")


def test_upload_and_status_flow(tmp_path):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("saved_posts.json", json.dumps({"saved_saved_media": []}))
    zip_bytes.seek(0)

    with patch("app.main.process_export_zip") as mock_process:
        fake_zip = tmp_path / "mock_download.zip"
        fake_zip.write_text("mock zip content")
        mock_process.return_value = (fake_zip, 5, 0)

        response = client.post(
            "/upload",
            files={"file": ("instagram_export.zip", zip_bytes.getvalue(), "application/zip")}
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        session_id = data["session_id"]

        status_res = client.get(f"/status/{session_id}")
        assert status_res.status_code == 200
        assert status_res.json()["session_id"] == session_id

        import time
        for _ in range(20):
            time.sleep(0.1)
            sess = session_manager.get_session(session_id)
            if sess and sess.state == "done":
                break

        final_status = client.get(f"/status/{session_id}").json()
        assert final_status["state"] == "done"
        assert final_status["has_download"] is True

        dl_res = client.get(f"/download/{session_id}")
        assert dl_res.status_code == 200
        assert dl_res.content == b"mock zip content"


def test_progress_stream_sse():
    session_id = "sse-test-session"
    session = session_manager.create_session(session_id)
    session_manager.update_session(session_id, state="done", total=10, current=10)

    with client.stream("GET", f"/progress/{session_id}") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = [line for line in response.iter_lines() if line]
        assert any("done" in l for l in lines)

    session_manager.cleanup_session(session_id)


def test_cancel_api_endpoint():
    session_id = "api-cancel-session"
    session = session_manager.create_session(session_id)
    assert session.session_dir.exists()

    res = client.post(f"/cancel/{session_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "cancelled"
    assert data["session_id"] == session_id
    assert data["success"] is True

    assert not session.session_dir.exists()
    assert session_manager.get_session(session_id) is None


def test_frontend_theme_and_cancel_elements():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'id="themeToggle"' in html
    assert 'id="cancelBtn"' in html
    assert 'savedge_theme' in html
    assert 'rel="canonical"' in html
    assert 'rel="icon"' in html
    assert 'id="guideNavLink"' in html
    assert 'id="export-guide"' in html
    assert "Your information and permissions" in html
    assert "STEP 1" in html
    assert "STEP 7" in html
