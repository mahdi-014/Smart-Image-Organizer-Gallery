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
from backend.api.deps import get_read_only_db, get_write_db, get_db_path, validate_thumbnail_path
from backend.api.schemas import (
    CategoryResponse,
    HealthResponse,
    ImageItemResponse,
    ImageListResponse,
    FolderValidateRequest,
    FolderValidateResponse,
    FolderBrowseResponse,
    FolderOpenRequest,
    FolderOpenResponse,
    ScanStartRequest,
    ScanStatusResponse,
    ClassifyStartResponse,
    ClassifyStatusResponse,
    CategoryOverrideRequest,
    CategoryOverrideResponse,
    OrganizePreviewRequest,
    OrganizeExecuteRequest,
    ImageRenameRequest,
    ImageRenameResponse,
    CatalogClearResponse,
)
from backend.db.session import init_db
from backend.db.repository import (
    list_images,
    count_images,
    get_image_by_id,
    get_categories,
    override_image_category,
    get_needs_review_images,
    update_image_proposed_filename,
)
from backend.core.folder_service import (
    validate_local_folder,
    browse_local_folder,
    open_in_file_explorer,
    check_folder_overlap,
    clear_staging_catalog,
)
from backend.core.renamer import sanitize_proposed_filename
from backend.core.scan_manager import coordinator
from backend.core.classifier import LocalVisionClassifier
from backend.core.organizer import (
    generate_organization_plan,
    execute_organization_plan,
    OrganizationPlan,
    OrganizationResult,
)


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
    Ensures runtime storage directories exist and migrations are applied on startup.
    """
    settings.ensure_directories()
    init_db()
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
            proposed_filename=row.get("proposed_filename"),
            visual_description=row.get("visual_description"),
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


# --- Organizer Workflow API Endpoints ---

@app.post("/api/folders/validate", response_model=FolderValidateResponse)
def validate_folder_route(payload: FolderValidateRequest) -> FolderValidateResponse:
    """Validates a local filesystem folder path for source or destination usage."""
    try:
        resolved = validate_local_folder(payload.folder_path, must_exist=payload.must_exist)
        return FolderValidateResponse(
            valid=True,
            resolved_path=str(resolved),
            exists=resolved.exists(),
        )
    except Exception as e:
        return FolderValidateResponse(
            valid=False,
            resolved_path=None,
            exists=False,
            error=str(e),
        )


@app.post("/api/folders/browse", response_model=FolderBrowseResponse)
def browse_folder_route() -> FolderBrowseResponse:
    """Opens native Windows directory selection dialog on host machine."""
    chosen = browse_local_folder()
    return FolderBrowseResponse(folder_path=chosen)


@app.post("/api/folders/open", response_model=FolderOpenResponse)
def open_folder_route(payload: FolderOpenRequest) -> FolderOpenResponse:
    """Opens target directory directly inside Windows File Explorer."""
    success = open_in_file_explorer(payload.folder_path)
    return FolderOpenResponse(
        success=success,
        message=f"Opened in File Explorer: {payload.folder_path}" if success else "Failed to open folder",
    )


@app.post("/api/scan/start", response_model=ScanStatusResponse)
def start_scan_route(payload: ScanStartRequest) -> ScanStatusResponse:
    """Initiates background directory scan of chosen source folder."""
    try:
        validated_src = validate_local_folder(payload.source_path, must_exist=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    validated_ex = None
    if payload.exclude_path:
        try:
            validated_ex = str(validate_local_folder(payload.exclude_path, must_exist=False))
        except Exception:
            pass

    started = coordinator.start_scan(str(validated_src), exclude_path=validated_ex, db_path=get_db_path())
    status = coordinator.get_scan_status()
    return ScanStatusResponse(**status)


@app.get("/api/scan/status", response_model=ScanStatusResponse)
def get_scan_status_route() -> ScanStatusResponse:
    """Polls live status of running or completed catalog scan."""
    return ScanStatusResponse(**coordinator.get_scan_status())


@app.post("/api/classify/start", response_model=ClassifyStartResponse)
def start_classification_route(db: sqlite3.Connection = Depends(get_read_only_db)) -> ClassifyStartResponse:
    """Runs local AI classification across unclassified catalog images."""
    try:
        classifier = LocalVisionClassifier()
        summary = classifier.classify_catalog(db_path=get_db_path())
        return ClassifyStartResponse(
            status="completed",
            total_processed=summary["total_processed"],
            classified_count=summary["classified_count"],
            needs_review_count=summary["needs_review_count"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/classify/status", response_model=ClassifyStatusResponse)
def get_classify_status_route() -> ClassifyStatusResponse:
    """Polls live status of background classification worker."""
    return ClassifyStatusResponse(**coordinator.get_classification_status())


@app.patch("/api/images/{image_id}/rename", response_model=ImageRenameResponse)
def rename_image_route(
    image_id: int = FastPath(..., ge=1),
    payload: ImageRenameRequest = ...,
    db: sqlite3.Connection = Depends(get_write_db),
) -> ImageRenameResponse:
    """Manually edits proposed filename for an image before dry-run and copying."""
    image = get_image_by_id(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    sanitized = sanitize_proposed_filename(payload.proposed_filename, original_filename=image["file_name"])
    success = update_image_proposed_filename(db, image_id, sanitized)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update filename.")

    return ImageRenameResponse(
        success=True,
        image_id=image_id,
        proposed_filename=sanitized,
    )


@app.patch("/api/images/{image_id}/category", response_model=CategoryOverrideResponse)
def override_image_category_route(
    image_id: int = FastPath(..., ge=1),
    payload: CategoryOverrideRequest = ...,
    db: sqlite3.Connection = Depends(get_write_db),
) -> CategoryOverrideResponse:
    """Manually reassigns category and approves an image, resolving review queue."""
    success = override_image_category(db, image_id, payload.category_id, approve=payload.approve)
    if not success:
        raise HTTPException(status_code=404, detail="Image not found.")
    return CategoryOverrideResponse(
        success=True,
        image_id=image_id,
        status="approved" if payload.approve else "classified",
    )


@app.post("/api/organize/preview", response_model=OrganizationPlan)
def organize_preview_route(
    payload: OrganizePreviewRequest,
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> OrganizationPlan:
    """Generates dry-run folder organization manifest without modifying files."""
    try:
        resolved_dest = validate_local_folder(payload.destination_dir, must_exist=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    plan = generate_organization_plan(
        destination_dir=str(resolved_dest),
        db_path=get_db_path(),
        image_ids=payload.image_ids,
        include_needs_review=payload.include_needs_review,
    )
    return plan


@app.post("/api/organize/execute", response_model=OrganizationResult)
def organize_execute_route(
    payload: OrganizeExecuteRequest,
    db: sqlite3.Connection = Depends(get_read_only_db),
) -> OrganizationResult:
    """Executes approved organization plan: copies files, verifies SHA-256, and logs operations."""
    try:
        resolved_dest = validate_local_folder(payload.destination_dir, must_exist=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    plan = generate_organization_plan(
        destination_dir=str(resolved_dest),
        db_path=get_db_path(),
        image_ids=payload.image_ids,
        include_needs_review=payload.include_needs_review,
    )
    result = execute_organization_plan(
        plan,
        db_path=get_db_path(),
        auto_remove_organized=payload.auto_remove_organized,
    )
    return result


@app.post("/api/catalog/clear", response_model=CatalogClearResponse)
def clear_catalog_route() -> CatalogClearResponse:
    """Clears all staged images from catalog and removes cached thumbnails."""
    cleared = clear_staging_catalog(db_path=get_db_path(), clear_thumbnails=True)
    return CatalogClearResponse(
        success=True,
        cleared_count=cleared,
        message=f"Cleared {cleared} images from catalog.",
    )


# Static files mount for Web Gallery frontend
FRONTEND_DIR = settings.project_root / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
