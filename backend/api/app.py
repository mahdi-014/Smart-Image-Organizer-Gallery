"""
FastAPI application definition and core route registration.
"""

from typing import Dict
from fastapi import FastAPI

from config.settings import settings

app = FastAPI(
    title=settings.app_name,
)


@app.get("/api/health")
def health_check() -> Dict[str, str]:
    """
    Return basic service health status and application metadata.
    """
    return {
        "status": "ok",
        "service": settings.app_name,
    }
