"""
FastAPI application definition and core route registration.
"""

import sqlite3
from typing import Dict
from fastapi import FastAPI, Depends, Query, Path as FastPath, HTTPException, status
from fastapi.responses import FileResponse

from config.settings import settings
from backend.api.deps import get_read_only_db, validate_thumbnail_path
from backend.api.schemas import ImageItemResponse, ImageListResponse
from backend.db.repository import list_images, count_images, get_image_by_id

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


@app.get("/api/images", response_model=ImageListResponse)
def get_images(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> ImageListResponse:
    """
    Return a paginated list of cataloged images with total matching count.
    """
    total = count_images(db)
    rows = list_images(db, limit=limit, offset=offset)

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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found.",
        )

    raw_thumbnail_path = image.get("thumbnail_path")
    if not raw_thumbnail_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not available.",
        )

    validated_path = validate_thumbnail_path(raw_thumbnail_path, settings.thumbnails_dir)
    if not validated_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not available.",
        )

    return FileResponse(
        path=validated_path,
        media_type="image/webp",
        filename=validated_path.name,
        content_disposition_type="inline",
    )
