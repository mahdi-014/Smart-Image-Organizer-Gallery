"""
Tests for API endpoints supporting the end-to-end File Organizer workflow:
Folder selection, scanning, classification, category override, dry-run preview,
and organization execution.
"""

from pathlib import Path
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image

from backend.api.app import app
from backend.api.deps import (
    get_read_only_db,
    get_write_db,
    open_read_only_connection,
    set_db_path_override,
)
from backend.core.hasher import compute_sha256
from backend.db.session import init_db, db_session
from backend.db import repository


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()
    set_db_path_override(None)


@pytest.fixture
def client(temp_db: Path) -> TestClient:
    set_db_path_override(temp_db)

    def override_ro_db():
        conn = open_read_only_connection(temp_db)
        try:
            yield conn
        finally:
            conn.close()

    def override_wr_db():
        with db_session(temp_db) as conn:
            yield conn

    app.dependency_overrides[get_read_only_db] = override_ro_db
    app.dependency_overrides[get_write_db] = override_wr_db
    return TestClient(app)


def test_validate_folder_api(client: TestClient, tmp_path: Path):
    """Verifies POST /api/folders/validate returns valid resolved paths."""
    res = client.post("/api/folders/validate", json={"folder_path": str(tmp_path), "must_exist": True})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["resolved_path"] == str(tmp_path.resolve())

    # Invalid nonexistent folder
    bad_res = client.post("/api/folders/validate", json={"folder_path": str(tmp_path / "nope"), "must_exist": True})
    assert bad_res.status_code == 200
    bad_data = bad_res.json()
    assert bad_data["valid"] is False
    assert "does not exist" in bad_data["error"]


def test_open_file_explorer_api(client: TestClient, tmp_path: Path):
    """Verifies POST /api/folders/open triggers explorer."""
    with patch("subprocess.Popen") as mock_popen:
        res = client.post("/api/folders/open", json={"folder_path": str(tmp_path)})
        assert res.status_code == 200
        assert res.json()["success"] is True
        mock_popen.assert_called_once()


def test_category_override_api(client: TestClient, temp_db: Path):
    """Verifies PATCH /api/images/{id}/category updates status to approved."""
    with db_session(temp_db) as conn:
        cats = repository.get_categories(conn)
        target_cat = cats[0]["id"]
        img_id = repository.upsert_image(conn, {
            "file_path": "C:/photos/test.jpg",
            "file_name": "test.jpg",
            "file_size": 100,
            "file_hash_sha256": "h_test",
            "phash": "dummy",
            "width": 100,
            "height": 100,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": None,
            "status": "needs_review",
            "primary_category_id": None,
        })

    patch_res = client.patch(f"/api/images/{img_id}/category", json={"category_id": target_cat, "approve": True})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "approved"


def test_organize_preview_and_execute_api(client: TestClient, tmp_path: Path, temp_db: Path):
    """Verifies POST /api/organize/preview and POST /api/organize/execute work end-to-end via API."""
    src_dir = tmp_path / "raw_photos"
    src_dir.mkdir()
    sample_file = src_dir / "sample.jpg"
    Image.new("RGB", (60, 60), "green").save(sample_file)

    dest_dir = tmp_path / "final_organized"

    with db_session(temp_db) as conn:
        cats = repository.get_categories(conn)
        cat_id = cats[0]["id"]
        repository.upsert_image(conn, {
            "file_path": str(sample_file),
            "file_name": "sample.jpg",
            "file_size": sample_file.stat().st_size,
            "file_hash_sha256": compute_sha256(sample_file),
            "phash": "dummy",
            "width": 60,
            "height": 60,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": None,
            "status": "classified",
            "primary_category_id": cat_id,
        })

    # 1. Preview
    prev_res = client.post("/api/organize/preview", json={"destination_dir": str(dest_dir)})
    assert prev_res.status_code == 200
    plan = prev_res.json()
    assert plan["total_files"] == 1
    assert len(plan["items"]) == 1

    # 2. Execute
    exec_res = client.post("/api/organize/execute", json={"destination_dir": str(dest_dir)})
    assert exec_res.status_code == 200
    result = exec_res.json()
    assert result["total_files"] == 1
    assert result["copied_count"] == 1
    assert result["verified_count"] == 1
    assert result["failed_count"] == 0


def test_scan_and_classify_api_workflow(client: TestClient, tmp_path: Path, temp_db: Path):
    """
    Verifies the complete scan and classification workflow via API endpoints.
    """
    src_dir = tmp_path / "camera_roll"
    src_dir.mkdir()
    for i in range(3):
        f = src_dir / f"img_{i}.png"
        Image.new("RGB", (40, 40), "white").save(f)

    # 1. Start scan
    scan_res = client.post("/api/scan/start", json={"source_path": str(src_dir)})
    assert scan_res.status_code == 200

    # 2. Poll status
    status_res = client.get("/api/scan/status")
    assert status_res.status_code == 200

    # Let thread complete
    import time
    for _ in range(20):
        s = client.get("/api/scan/status").json()
        if s["is_complete"] or not s["is_running"]:
            break
        time.sleep(0.1)

    # 3. Classify
    cls_res = client.post("/api/classify/start")
    assert cls_res.status_code == 200
    cls_data = cls_res.json()
    assert cls_data["status"] == "completed"
    assert cls_data["total_processed"] >= 3



def test_image_rename_api(client: TestClient, temp_db: Path):
    """Verifies PATCH /api/images/{id}/rename sanitizes and saves custom proposed filenames."""
    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": "C:/photos/IMG_0099.jpg",
            "file_name": "IMG_0099.jpg",
            "file_size": 500,
            "file_hash_sha256": "h_rename",
            "phash": "dummy",
            "width": 80,
            "height": 80,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": None,
            "status": "scanned",
            "primary_category_id": None,
        })

    # 1. Successful rename with custom description and punctuation
    res = client.patch(f"/api/images/{img_id}/rename", json={"proposed_filename": "Happy Golden Retriever Running! (2026).jpg"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["proposed_filename"] == "happy-golden-retriever-running-2026.jpg"

    # 2. Verify reflected in GET /api/images
    get_res = client.get("/api/images")
    assert get_res.status_code == 200
    images = get_res.json()["items"]
    matched = next(i for i in images if i["id"] == img_id)
    assert matched["proposed_filename"] == "happy-golden-retriever-running-2026.jpg"

    # 3. Nonexistent image returns 404
    bad_res = client.patch("/api/images/999999/rename", json={"proposed_filename": "test.jpg"})
    assert bad_res.status_code == 404


def test_clear_catalog_api(client: TestClient, temp_db: Path):
    """Verifies POST /api/catalog/clear purges all staging catalog records."""
    with db_session(temp_db) as conn:
        repository.upsert_image(conn, {
            "file_path": "C:/photos/to_clear.jpg",
            "file_name": "to_clear.jpg",
            "file_size": 1234,
            "file_hash_sha256": "h_clear",
            "phash": "dummy",
            "width": 100,
            "height": 100,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": None,
            "status": "scanned",
            "primary_category_id": None,
        })
        assert repository.count_images(conn) >= 1

    res = client.post("/api/catalog/clear")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["cleared_count"] >= 1

    # Verify catalog is empty now
    get_res = client.get("/api/images")
    assert get_res.status_code == 200
    assert get_res.json()["total"] == 0
