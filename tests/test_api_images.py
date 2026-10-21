"""
Tests for the read-only paginated image list API endpoint (GET /api/images).
"""

import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_read_only_db, open_read_only_connection
from backend.db.session import init_db, db_session
from backend.db.repository import upsert_image


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """Ensure FastAPI dependency overrides are safely cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    """Provides a TestClient for making API requests."""
    return TestClient(app)


def seed_synthetic_catalog(db_path: Path, count: int = 5) -> None:
    """Initialize schema and seed synthetic image records into a temporary database."""
    init_db(db_path)
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, code_name, display_name FROM categories LIMIT 1")
        cat_row = cursor.fetchone()
        cat_id = cat_row["id"] if cat_row else None

        for i in range(1, count + 1):
            has_cat = (i % 2 == 1) and (cat_id is not None)
            has_thumb = (i % 2 == 1)
            data = {
                "file_path": f"C:\\synthetic_source\\photos\\secret_subfolder\\photo_{i:03d}.jpg",
                "file_name": f"photo_{i:03d}.jpg",
                "file_size": 204800 + i * 1024,
                "file_hash_sha256": f"supersecretsha256hash_{i:03d}_" + "f" * 40,
                "phash": f"secretphash_{i:03d}",
                "width": 1920,
                "height": 1080,
                "file_format": "JPEG",
                "date_taken": f"2025-02-{i:02d}T10:30:00",
                "date_modified": f"2025-02-{i:02d}T12:00:00",
                "thumbnail_path": f"C:\\synthetic_source\\thumbs\\thumb_{i:03d}.webp" if has_thumb else None,
                "status": "scanned",
                "primary_category_id": cat_id if has_cat else None,
            }
            upsert_image(conn, data)


def set_read_only_db_override(db_path: Path) -> None:
    """Override get_read_only_db dependency pointing to the specified database path."""
    def _override():
        conn = open_read_only_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_read_only_db] = _override


def test_images_populated_catalog_structure(tmp_path: Path, client: TestClient):
    """Verify populated catalog returns 200 OK and expected response fields."""
    db_path = tmp_path / "populated.db"
    seed_synthetic_catalog(db_path, count=5)
    set_read_only_db_override(db_path)

    response = client.get("/api/images")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 5
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 5

    first_item = data["items"][0]
    expected_keys = {
        "id", "file_name", "file_size", "width", "height", "file_format",
        "date_taken", "date_modified", "status", "category_name",
        "category_code", "has_thumbnail"
    }
    assert set(first_item.keys()) == expected_keys
    assert first_item["file_format"] == "JPEG"
    assert first_item["width"] == 1920
    assert first_item["height"] == 1080
    assert isinstance(first_item["has_thumbnail"], bool)


def test_images_pagination_limits_and_offsets(tmp_path: Path, client: TestClient):
    """Verify limit and offset slice the items correctly without altering total count."""
    db_path = tmp_path / "pagination.db"
    seed_synthetic_catalog(db_path, count=5)
    set_read_only_db_override(db_path)

    # Page 1: limit 2, offset 0
    resp1 = client.get("/api/images?limit=2&offset=0")
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["total"] == 5
    assert d1["limit"] == 2
    assert d1["offset"] == 0
    assert len(d1["items"]) == 2
    ids_page1 = [item["id"] for item in d1["items"]]

    # Page 2: limit 2, offset 2
    resp2 = client.get("/api/images?limit=2&offset=2")
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["total"] == 5
    assert d2["limit"] == 2
    assert d2["offset"] == 2
    assert len(d2["items"]) == 2
    ids_page2 = [item["id"] for item in d2["items"]]

    # Page 3: limit 2, offset 4
    resp3 = client.get("/api/images?limit=2&offset=4")
    assert resp3.status_code == 200
    d3 = resp3.json()
    assert d3["total"] == 5
    assert len(d3["items"]) == 1
    ids_page3 = [item["id"] for item in d3["items"]]

    # Ensure all returned items across pages are distinct
    all_paged_ids = ids_page1 + ids_page2 + ids_page3
    assert len(all_paged_ids) == 5
    assert len(set(all_paged_ids)) == 5

    # Offset beyond total
    resp_empty = client.get("/api/images?limit=2&offset=10")
    assert resp_empty.status_code == 200
    d_empty = resp_empty.json()
    assert d_empty["total"] == 5
    assert d_empty["items"] == []


def test_images_total_represents_full_catalog_count(tmp_path: Path, client: TestClient):
    """Verify total represents complete matching catalog count, not page size."""
    db_path = tmp_path / "total_check.db"
    seed_synthetic_catalog(db_path, count=5)
    set_read_only_db_override(db_path)

    response = client.get("/api/images?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 5


def test_images_empty_catalog(tmp_path: Path, client: TestClient):
    """Verify an empty database catalog returns HTTP 200 with items: [] and total: 0."""
    db_path = tmp_path / "empty.db"
    init_db(db_path)
    set_read_only_db_override(db_path)

    response = client.get("/api/images")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_images_query_validation_errors(client: TestClient):
    """Verify FastAPI query validation rejects invalid limit and offset values with 422."""
    # limit below 1
    assert client.get("/api/images?limit=0").status_code == 422
    # limit above 100
    assert client.get("/api/images?limit=101").status_code == 422
    # negative offset
    assert client.get("/api/images?offset=-1").status_code == 422
    # non-integer limit
    assert client.get("/api/images?limit=invalid").status_code == 422


def test_images_does_not_expose_paths_or_hashes(tmp_path: Path, client: TestClient):
    """Verify sensitive filesystem paths, hashes, and thumbnail paths are never leaked."""
    db_path = tmp_path / "security_check.db"
    seed_synthetic_catalog(db_path, count=3)
    set_read_only_db_override(db_path)

    response = client.get("/api/images")
    assert response.status_code == 200
    raw_response_text = response.text

    # Verify column keys and sensitive values are excluded
    assert "file_path" not in raw_response_text
    assert "file_hash_sha256" not in raw_response_text
    assert "thumbnail_path" not in raw_response_text
    assert "secret_subfolder" not in raw_response_text
    assert "supersecretsha256hash" not in raw_response_text
    assert "secretphash" not in raw_response_text


def test_images_missing_database_returns_503(tmp_path: Path, client: TestClient):
    """Verify missing database returns controlled 503 without leaking paths."""
    missing_db = tmp_path / "missing_catalog.db"
    set_read_only_db_override(missing_db)

    response = client.get("/api/images")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database catalog is not initialized or unavailable."
    assert str(missing_db) not in response.text


def test_images_uninitialized_database_returns_503(tmp_path: Path, client: TestClient):
    """Verify uninitialized database file returns controlled 503."""
    blank_db = tmp_path / "blank.db"
    sqlite3.connect(str(blank_db)).close()
    set_read_only_db_override(blank_db)

    response = client.get("/api/images")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database catalog schema is not initialized."
    assert str(blank_db) not in response.text


def test_health_endpoint_remains_operational(tmp_path: Path, client: TestClient):
    """Verify GET /api/health operates normally even when catalog is missing."""
    missing_db = tmp_path / "missing.db"
    set_read_only_db_override(missing_db)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Smart Image Organizer & Gallery",
    }
