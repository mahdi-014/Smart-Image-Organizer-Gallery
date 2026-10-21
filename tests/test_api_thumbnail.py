"""
Tests for the secure thumbnail serving endpoint (GET /api/images/{image_id}/thumbnail).
"""

import os
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from backend.api.app import app
from backend.api.deps import get_read_only_db, open_read_only_connection, validate_thumbnail_path
from backend.db.session import init_db, db_session
from backend.db.repository import upsert_image, get_image_by_id


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """Ensure FastAPI dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    """Provides a TestClient for making API requests."""
    return TestClient(app)


def set_read_only_db_override(db_path: Path) -> None:
    """Override get_read_only_db to point to a test database."""
    def _override():
        conn = open_read_only_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_read_only_db] = _override


def create_synthetic_image(conn: sqlite3.Connection, file_name: str, thumb_path: str = None) -> int:
    """Helper to insert a synthetic image record returning the assigned integer ID."""
    data = {
        "file_path": f"C:\\synthetic_source\\photos\\{file_name}",
        "file_name": file_name,
        "file_size": 204800,
        "file_hash_sha256": f"hash_sha256_{file_name}",
        "phash": "dummy_phash_val",
        "width": 1280,
        "height": 720,
        "file_format": "JPEG",
        "date_taken": "2025-01-10T10:00:00",
        "date_modified": "2025-01-10T12:00:00",
        "thumbnail_path": thumb_path,
        "status": "scanned",
        "primary_category_id": None,
    }
    return upsert_image(conn, data)


def test_thumbnail_existing_returns_200_and_bytes_and_headers(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify an existing valid thumbnail returns HTTP 200, webp content type, and inline disposition."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    # Create dummy WebP file bytes
    fake_webp_bytes = b"RIFF\x20\x00\x00\x00WEBPVP8 \x14\x00\x00\x00\xb0\x01\x00\x00"
    thumb_file = test_thumbs_dir / "valid_image.webp"
    thumb_file.write_bytes(fake_webp_bytes)

    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "sample.jpg", str(thumb_file))

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 200
    assert response.content == fake_webp_bytes
    assert response.headers["content-type"].startswith("image/webp")
    content_disp = response.headers.get("content-disposition", "").lower()
    assert "inline" in content_disp


def test_thumbnail_unknown_image_id_returns_404(tmp_path: Path, client: TestClient):
    """Verify requesting a non-existent image ID returns HTTP 404."""
    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    set_read_only_db_override(db_path)

    response = client.get("/api/images/99999/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Image not found."


def test_thumbnail_null_path_returns_404(tmp_path: Path, client: TestClient):
    """Verify an image record with null thumbnail_path returns HTTP 404."""
    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "no_thumb.jpg", thumb_path=None)

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available."


def test_thumbnail_empty_path_returns_404(tmp_path: Path, client: TestClient):
    """Verify an image record with empty string thumbnail_path returns HTTP 404."""
    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "empty_thumb.jpg", thumb_path="")

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available."


def test_thumbnail_missing_file_returns_404(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify a thumbnail_path pointing to a non-existent file returns HTTP 404 without leaking path."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    missing_file = test_thumbs_dir / "ghost.webp"
    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "missing.jpg", str(missing_file))

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available."
    assert "ghost.webp" not in response.text


def test_thumbnail_outside_directory_rejected(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify that a path pointing outside the allowed thumbnails directory is rejected."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    outside_file = tmp_path / "secret_document.txt"
    outside_file.write_bytes(b"CONFIDENTIAL_DATA")

    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "leak_attempt.jpg", str(outside_file))

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available."
    assert "CONFIDENTIAL_DATA" not in response.text
    assert "secret_document" not in response.text


def test_thumbnail_traversal_escape_rejected(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify that path traversal (../..) attempting to escape thumbnail directory is rejected."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    outside_target = tmp_path / "traversal_target.webp"
    outside_target.write_bytes(b"EXPLOIT_PAYLOAD")

    traversal_path = f"{test_thumbs_dir}/../traversal_target.webp"

    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "traversal.jpg", traversal_path)

    set_read_only_db_override(db_path)

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available."
    assert "EXPLOIT_PAYLOAD" not in response.text


def test_thumbnail_symlink_escape_rejected(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify symlink pointing outside the thumbnails directory is rejected if symlinks are supported."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    outside_secret = tmp_path / "sensitive.txt"
    outside_secret.write_bytes(b"TOP_SECRET_SYS_FILE")

    symlink_path = test_thumbs_dir / "symlink_escape.webp"

    try:
        os.symlink(outside_secret, symlink_path)
        symlink_supported = True
    except (OSError, NotImplementedError):
        symlink_supported = False

    if symlink_supported:
        db_path = tmp_path / "test_thumb.db"
        init_db(db_path)
        with db_session(db_path) as conn:
            img_id = create_synthetic_image(conn, "symlink_img.jpg", str(symlink_path))

        set_read_only_db_override(db_path)

        response = client.get(f"/api/images/{img_id}/thumbnail")
        assert response.status_code == 404
        assert response.json()["detail"] == "Thumbnail not available."
        assert "TOP_SECRET_SYS_FILE" not in response.text
    else:
        # Handled explicitly as noted in project requirements for non-admin Windows environments
        assert not symlink_supported


def test_thumbnail_read_only_guarantee_no_generation_or_mutation(
    tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify endpoint never creates a thumbnail file or mutates the database on missing thumbnail."""
    test_thumbs_dir = tmp_path / "thumbnails"
    test_thumbs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs_dir)

    db_path = tmp_path / "test_thumb.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        img_id = create_synthetic_image(conn, "pure_read_only.jpg", thumb_path=None)

    set_read_only_db_override(db_path)

    # Initial snapshot of thumbnails directory
    initial_files = list(test_thumbs_dir.glob("*"))
    assert initial_files == []

    response = client.get(f"/api/images/{img_id}/thumbnail")
    assert response.status_code == 404

    # Confirm no file was created in thumbnail cache
    files_after = list(test_thumbs_dir.glob("*"))
    assert files_after == []

    # Confirm database record was not altered
    with db_session(db_path) as conn:
        record = get_image_by_id(conn, img_id)
        assert record["thumbnail_path"] is None
        assert record["status"] == "scanned"


def test_thumbnail_query_validation_errors(client: TestClient):
    """Verify invalid image_id parameter formats return HTTP 422."""
    assert client.get("/api/images/0/thumbnail").status_code == 422
    assert client.get("/api/images/-1/thumbnail").status_code == 422
    assert client.get("/api/images/invalid/thumbnail").status_code == 422


def test_validate_thumbnail_path_unit_behavior(tmp_path: Path):
    """Direct unit tests for the validate_thumbnail_path security helper."""
    allowed = tmp_path / "thumbs"
    allowed.mkdir()
    valid_file = allowed / "good.webp"
    valid_file.write_bytes(b"good")

    assert validate_thumbnail_path(None, allowed) is None
    assert validate_thumbnail_path("", allowed) is None
    assert validate_thumbnail_path("   ", allowed) is None
    assert validate_thumbnail_path(str(valid_file), allowed) == valid_file.resolve()
    assert validate_thumbnail_path(str(allowed), allowed) is None  # Directory itself
    assert validate_thumbnail_path(str(tmp_path / "missing.webp"), allowed) is None
