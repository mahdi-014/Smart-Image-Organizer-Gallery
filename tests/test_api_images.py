"""
Tests for the read-only paginated image list API endpoint (GET /api/images).
Covers baseline behavior, filter parameters, pagination, security, and error handling.
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


def _make_filter_db(tmp_path: Path) -> tuple:
    """
    Create a test database seeded with a known set of images across two
    categories and two distinct statuses.  Returns (db_path, cat_a_id, cat_b_id).
    """
    db_path = tmp_path / "filter_test.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM categories ORDER BY id LIMIT 2")
        rows = c.fetchall()
        cat_a_id = rows[0]["id"]
        cat_b_id = rows[1]["id"] if len(rows) > 1 else None

        images = [
            # name,              status,         cat
            ("vacation_beach.jpg", "scanned",    cat_a_id),
            ("vacation_mountains.jpg", "approved", cat_a_id),
            ("pet_dog.jpg",      "scanned",       cat_b_id),
            ("pet_cat.jpg",      "classified",    cat_b_id),
            ("invoice_2025.jpg", "approved",      None),
            ("random_stuff.jpg", "scanned",       None),
        ]
        for idx, (name, st, cat) in enumerate(images, start=1):
            upsert_image(conn, {
                "file_path": f"C:\\photos\\{name}",
                "file_name": name,
                "file_size": 50000 + idx * 100,
                "file_hash_sha256": f"filterdb_hash_{idx:04d}" + "a" * 44,
                "phash": f"fphash_{idx}",
                "width": 1280, "height": 720,
                "file_format": "JPEG",
                "date_taken": f"2025-03-{idx:02d}T09:00:00",
                "date_modified": f"2025-03-{idx:02d}T10:00:00",
                "thumbnail_path": None,
                "status": st,
                "primary_category_id": cat,
            })
    return db_path, cat_a_id, cat_b_id


# ---------------------------------------------------------------------------
# Baseline (existing) behavior tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Filter parameter tests (T2.4)
# ---------------------------------------------------------------------------

def test_filter_no_filters_preserves_existing_behavior(tmp_path: Path, client: TestClient):
    """No filters: all images returned, totals unaffected."""
    db_path, cat_a_id, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get("/api/images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert len(data["items"]) == 6


def test_filter_category_id_returns_matching_images(tmp_path: Path, client: TestClient):
    """category_id filter returns only images in that category."""
    db_path, cat_a_id, cat_b_id = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get(f"/api/images?category_id={cat_a_id}")
    assert resp.status_code == 200
    data = resp.json()
    # cat_a has 2 images: vacation_beach + vacation_mountains
    assert data["total"] == 2
    assert len(data["items"]) == 2
    names = {item["file_name"] for item in data["items"]}
    assert "vacation_beach.jpg" in names
    assert "vacation_mountains.jpg" in names

    if cat_b_id:
        resp_b = client.get(f"/api/images?category_id={cat_b_id}")
        assert resp_b.status_code == 200
        assert resp_b.json()["total"] == 2


def test_filter_status_returns_matching_images(tmp_path: Path, client: TestClient):
    """status filter returns only images with that processing status."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp_scanned = client.get("/api/images?status=scanned")
    assert resp_scanned.status_code == 200
    data_scanned = resp_scanned.json()
    # scanned: vacation_beach, pet_dog, random_stuff -> 3
    assert data_scanned["total"] == 3
    for item in data_scanned["items"]:
        assert item["status"] == "scanned"

    resp_approved = client.get("/api/images?status=approved")
    assert resp_approved.status_code == 200
    data_approved = resp_approved.json()
    # approved: vacation_mountains, invoice_2025 -> 2
    assert data_approved["total"] == 2
    for item in data_approved["items"]:
        assert item["status"] == "approved"


def test_filter_q_finds_by_filename(tmp_path: Path, client: TestClient):
    """q parameter matches images whose filename contains the search term."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get("/api/images?q=vacation")
    assert resp.status_code == 200
    data = resp.json()
    # vacation_beach.jpg + vacation_mountains.jpg -> 2
    assert data["total"] == 2
    names = {item["file_name"] for item in data["items"]}
    assert "vacation_beach.jpg" in names
    assert "vacation_mountains.jpg" in names


def test_filter_q_no_match_returns_empty(tmp_path: Path, client: TestClient):
    """A search with no matches returns an empty list and total: 0."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get("/api/images?q=xyznonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_filter_combined_category_status_q(tmp_path: Path, client: TestClient):
    """All three filters combined return only records matching all conditions."""
    db_path, cat_a_id, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    # cat_a + status=scanned + q=vacation -> only vacation_beach (scanned in cat_a)
    resp = client.get(f"/api/images?category_id={cat_a_id}&status=scanned&q=vacation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["file_name"] == "vacation_beach.jpg"


def test_filter_pagination_with_filters_applied(tmp_path: Path, client: TestClient):
    """Pagination works correctly when filters are active."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    # 3 scanned images total; page with limit=2
    resp_p1 = client.get("/api/images?status=scanned&limit=2&offset=0")
    assert resp_p1.status_code == 200
    d1 = resp_p1.json()
    assert d1["total"] == 3
    assert len(d1["items"]) == 2

    resp_p2 = client.get("/api/images?status=scanned&limit=2&offset=2")
    assert resp_p2.status_code == 200
    d2 = resp_p2.json()
    assert d2["total"] == 3
    assert len(d2["items"]) == 1

    # No overlap between pages
    ids_p1 = {item["id"] for item in d1["items"]}
    ids_p2 = {item["id"] for item in d2["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_filter_total_counts_all_matching_not_just_page(tmp_path: Path, client: TestClient):
    """total reflects all matched records regardless of limit."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get("/api/images?status=scanned&limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 3  # total matching, not page size


def test_filter_q_empty_string_treats_as_no_filter(tmp_path: Path, client: TestClient):
    """An empty q string is treated as if no search filter was supplied."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp_empty = client.get("/api/images?q=")
    assert resp_empty.status_code == 200
    assert resp_empty.json()["total"] == 6

    resp_whitespace = client.get("/api/images?q=   ")
    assert resp_whitespace.status_code == 200
    assert resp_whitespace.json()["total"] == 6


def test_filter_q_whitespace_trimmed(tmp_path: Path, client: TestClient):
    """Leading and trailing whitespace in q is trimmed before searching."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp_padded = client.get("/api/images?q=  vacation  ")
    assert resp_padded.status_code == 200
    data = resp_padded.json()
    # Should match the same 2 vacation images as unpadded search
    assert data["total"] == 2


def test_filter_invalid_category_id_returns_422(client: TestClient):
    """category_id of 0 or negative is rejected with HTTP 422."""
    assert client.get("/api/images?category_id=0").status_code == 422
    assert client.get("/api/images?category_id=-1").status_code == 422
    assert client.get("/api/images?category_id=abc").status_code == 422


def test_filter_invalid_status_returns_422(client: TestClient):
    """An unrecognized status value is rejected with HTTP 422."""
    assert client.get("/api/images?status=invalid_status").status_code == 422
    assert client.get("/api/images?status=SCANNED").status_code == 422
    assert client.get("/api/images?status=deleted").status_code == 422


def test_filter_q_exceeding_max_length_returns_422(client: TestClient):
    """A q value longer than 200 characters is rejected with HTTP 422."""
    long_q = "x" * 201
    assert client.get(f"/api/images?q={long_q}").status_code == 422


def test_filter_security_paths_not_exposed_with_filters(tmp_path: Path, client: TestClient):
    """Filtered responses must not expose internal paths or hashes."""
    db_path, _, _ = _make_filter_db(tmp_path)
    set_read_only_db_override(db_path)

    resp = client.get("/api/images?q=vacation")
    assert resp.status_code == 200
    text = resp.text

    assert "file_path" not in text
    assert "file_hash_sha256" not in text
    assert "thumbnail_path" not in text
    assert "filterdb_hash" not in text
    assert "C:\\photos" not in text
