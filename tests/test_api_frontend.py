"""
Integration tests for the Web Gallery API contract consumed by the frontend.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_read_only_db, open_read_only_connection
from backend.db.session import init_db, db_session
from backend.db import repository


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(temp_db: Path) -> TestClient:
    def override_db():
        conn = open_read_only_connection(temp_db)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_read_only_db] = override_db
    return TestClient(app)


def test_frontend_full_api_workflow(client: TestClient, temp_db: Path):
    """
    Simulates the exact API calls made sequentially by the frontend app.js:
    1. GET /api/health
    2. GET /api/categories
    3. GET /api/images (initial page load)
    4. GET /api/images with filters (category, status, query)
    """
    # 1. Health check
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # 2. Categories load
    cat_res = client.get("/api/categories")
    assert cat_res.status_code == 200
    categories = cat_res.json()
    assert len(categories) > 0
    cat_id = categories[0]["id"]

    # Seed images in database
    with db_session(temp_db) as conn:
        for i in range(1, 10):
            repository.upsert_image(conn, {
                "file_path": f"C:/photos/vacation_{i}.jpg",
                "file_name": f"vacation_{i}.jpg",
                "file_size": 1024 * i,
                "file_hash_sha256": f"hash_{i}",
                "phash": "dummy",
                "width": 1920,
                "height": 1080,
                "file_format": "JPEG",
                "date_taken": f"2024-06-0{i}T12:00:00",
                "date_modified": f"2024-06-0{i}T12:00:00",
                "thumbnail_path": None,
                "status": "classified" if i % 2 == 0 else "scanned",
                "primary_category_id": cat_id if i <= 5 else None,
            })

    # 3. Initial gallery load (page 1, limit 4)
    images_res = client.get("/api/images?limit=4&offset=0")
    assert images_res.status_code == 200
    data = images_res.json()
    assert data["total"] == 9
    assert len(data["items"]) == 4

    # 4. Filter by category
    cat_filter_res = client.get(f"/api/images?limit=10&offset=0&category_id={cat_id}")
    assert cat_filter_res.status_code == 200
    cat_data = cat_filter_res.json()
    assert cat_data["total"] == 5

    # 5. Filter by status
    status_res = client.get("/api/images?limit=10&offset=0&status=classified")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["total"] == 4

    # 6. Search query
    search_res = client.get("/api/images?limit=10&offset=0&q=vacation_3")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["file_name"] == "vacation_3.jpg"

    # 7. No results search
    empty_res = client.get("/api/images?limit=10&offset=0&q=nonexistent_file_pattern")
    assert empty_res.status_code == 200
    empty_data = empty_res.json()
    assert empty_data["total"] == 0
    assert empty_data["items"] == []

