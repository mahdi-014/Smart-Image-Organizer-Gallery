"""
FastAPI application definition and core route registration.
"""

from contextlib import asynccontextmanager
import sqlite3
from enum import Enum
from typing import Dict, List, Optional
from fastapi import FastAPI, Depends, Query, Path as FastPath, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from backend.api.deps import get_read_only_db, validate_thumbnail_path
from backend.api.schemas import (
    CategoryResponse,
    HealthResponse,
    ImageItemResponse,
    ImageListResponse,
)
from backend.db.repository import list_images, count_images, get_image_by_id, get_categories


# Supported image processing status values — must match schema definition exactly.
# Schema comment: 'scanned', 'classified', 'needs_review', 'approved', 'organized'
class ImageStatus(str, Enum):
    scanned = "scanned"
    classified = "classified"
    needs_review = "needs_review"
    approved = "approved"
    organized = "organized"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Explicit application lifecycle management.
    Ensures runtime storage directories exist when the server starts.
    """
    settings.ensure_directories()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    Return basic service health status and application metadata.
    """
    return {
        "status": "ok",
        "service": settings.app_name,
    }


@app.get("/api/images", response_model=ImageListResponse)
def get_images(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category_id: Optional[int] = Query(default=None, ge=1, description="Filter by primary category ID."),
    status: Optional[ImageStatus] = Query(default=None, description="Filter by processing status."),
    q: Optional[str] = Query(default=None, max_length=200, description="Search images by filename."),
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> ImageListResponse:
    """
    Return a paginated, optionally filtered list of cataloged images.

    Optional filters:
    - category_id: integer, returns images belonging to the specified category.
    - status: one of scanned | classified | needs_review | approved | organized.
    - q: text search on filename; leading/trailing whitespace is stripped.

    total reflects the count of records matching the active filters, not the
    total catalog size.
    """
    # Normalize the search string: blank/whitespace-only becomes None (no filter).
    search_query: Optional[str] = q.strip() if q and q.strip() else None
    status_value: Optional[str] = status.value if status else None

    total = count_images(db, category_id=category_id, status=status_value, search_query=search_query)
    rows = list_images(db, limit=limit, offset=offset, category_id=category_id, status=status_value, search_query=search_query)

    items = [
        ImageItemResponse(
            id=row["id"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            width=row.get("width"),
            height=row.get("height"),
            file_format=row.get("file_format"),
            date_taken=row.get("date_taken"),
            date_modified=row["date_modified"],
            status=row["status"],
            category_name=row.get("category_name"),
            category_code=row.get("category_code"),
            has_thumbnail=bool(row.get("thumbnail_path")),
        )
        for row in rows
    ]

    return ImageListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/images/{image_id}/thumbnail",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"image/webp": {}},
            "description": "Pre-generated WebP thumbnail for the image.",
        },
        404: {
            "description": "Image or thumbnail not found.",
        },
    },
)
def get_image_thumbnail(
    image_id: int = FastPath(..., ge=1, description="Unique integer ID of the image record"),
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> FileResponse:
    """
    Return the existing WebP thumbnail for a cataloged image.
    Strictly read-only; does not generate or alter files.
    """
    image = get_image_by_id(db, image_id)
    if not image:
        raise HTTPException(
            status_code=404,
            detail="Image not found.",
        )

    raw_thumbnail_path = image.get("thumbnail_path")
    if not raw_thumbnail_path:
        raise HTTPException(
            status_code=404,
            detail="Thumbnail not available.",
        )

    validated_path = validate_thumbnail_path(raw_thumbnail_path, settings.thumbnails_dir)
    if not validated_path:
        raise HTTPException(
            status_code=404,
            detail="Thumbnail not available.",
        )

    return FileResponse(
        path=validated_path,
        media_type="image/webp",
        filename=validated_path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

@app.get("/api/categories", response_model=List[CategoryResponse])
def get_active_categories(
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> List[CategoryResponse]:
    """
    Return all active categories for UI filter dropdowns and taxonomy display.
    """
    categories = get_categories(db)
    return [CategoryResponse.model_validate(cat) for cat in categories]


# Static files mount for Web Gallery frontend
FRONTEND_DIR = settings.project_root / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
