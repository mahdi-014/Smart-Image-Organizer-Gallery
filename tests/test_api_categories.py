"""
Tests for Categories API endpoint and Frontend static serving.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_read_only_db, open_read_only_connection
from backend.db.session import init_db


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


def test_get_categories_returns_active_categories(client: TestClient, temp_db: Path):
    """
    Verifies that GET /api/categories returns the seeded active categories.
    """
    response = client.get("/api/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "id" in first
    assert "code_name" in first
    assert "display_name" in first


def test_root_serves_html_frontend(client: TestClient):
    """
    Verifies that GET / returns the frontend HTML document with 200 status.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<!doctype html>" in response.text.lower()
    assert "Smart Image Organizer & Gallery" in response.text


def test_static_assets_are_served(client: TestClient):
    """
    Verifies that static assets (style.css, app.js) are accessible.
    """
    css_res = client.get("/style.css")
    assert css_res.status_code == 200
    assert "text/css" in css_res.headers.get("content-type", "")

    js_res = client.get("/app.js")
    assert js_res.status_code == 200
    content_type = js_res.headers.get("content-type", "")
    assert ("javascript" in content_type or "text/plain" in content_type)

