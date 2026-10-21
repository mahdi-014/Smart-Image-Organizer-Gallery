"""
Tests for FastAPI application foundation and health check endpoint.
"""

from fastapi.testclient import TestClient

from backend.api.app import app
from config.settings import settings


client = TestClient(app)


def test_app_title_matches_settings():
    """Verify FastAPI application instance is configured with settings app_name."""
    assert app.title == settings.app_name


def test_health_check_status_code_and_payload():
    """Verify GET /api/health returns HTTP 200 with JSON payload."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": settings.app_name,
    }


def test_health_check_uses_typed_pydantic_response_model():
    """Verify that GET /api/health route is configured with typed HealthResponse model."""
    from backend.api.schemas import HealthResponse
    route = next(r for r in app.routes if getattr(r, "path", None) == "/api/health")
    assert getattr(route, "response_model", None) is HealthResponse
