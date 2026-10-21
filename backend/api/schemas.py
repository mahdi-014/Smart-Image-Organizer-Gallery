"""
Pydantic schemas for API request validation and response serialization.
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """
    Service health check response payload.
    """
    status: str
    service: str


class CategoryResponse(BaseModel):
    """
    Active category representation for UI taxonomy and filtering.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    code_name: str
    display_name: str
    description: Optional[str] = None


class ImageItemResponse(BaseModel):
    """
    Public metadata representation of a single cataloged image.
    Sensitive source filesystem paths and hash details are excluded.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    file_format: Optional[str] = None
    date_taken: Optional[str] = None
    date_modified: str
    status: str
    category_name: Optional[str] = None
    category_code: Optional[str] = None
    has_thumbnail: bool
    proposed_filename: Optional[str] = None
    visual_description: Optional[str] = None


class ImageListResponse(BaseModel):
    """
    Paginated list response containing images and total catalog count.
    """
    items: List[ImageItemResponse]
    total: int
    limit: int
    offset: int


# --- Organizer Workflow Schemas ---

class FolderValidateRequest(BaseModel):
    folder_path: str
    must_exist: bool = True


class FolderValidateResponse(BaseModel):
    valid: bool
    resolved_path: Optional[str] = None
    exists: bool = False
    error: Optional[str] = None


class FolderBrowseResponse(BaseModel):
    folder_path: Optional[str] = None


class FolderOpenRequest(BaseModel):
    folder_path: str


class FolderOpenResponse(BaseModel):
    success: bool
    message: str


class ScanStartRequest(BaseModel):
    source_path: str
    exclude_path: Optional[str] = None


class ScanStatusResponse(BaseModel):
    is_running: bool
    source_path: Optional[str] = None
    total_found: int
    processed_count: int
    skipped_count: int
    error_count: int
    is_complete: bool
    errors: List[str]


class ClassifyStartResponse(BaseModel):
    status: str
    total_processed: int
    classified_count: int
    needs_review_count: int


class ClassifyStatusResponse(BaseModel):
    is_running: bool
    processed: int
    total: int
    classified_count: int
    needs_review_count: int
    is_complete: bool


class CategoryOverrideRequest(BaseModel):
    category_id: int
    approve: bool = True


class CategoryOverrideResponse(BaseModel):
    success: bool
    image_id: int
    status: str


class OrganizePreviewRequest(BaseModel):
    destination_dir: str
    image_ids: Optional[List[int]] = None
    include_needs_review: bool = False


class OrganizeExecuteRequest(BaseModel):
    destination_dir: str
    image_ids: Optional[List[int]] = None
    include_needs_review: bool = False


class ImageRenameRequest(BaseModel):
    """Request payload to manually edit the proposed semantic filename of an image."""
    proposed_filename: str


class ImageRenameResponse(BaseModel):
    """Response payload confirming updated proposed filename."""
    success: bool
    image_id: int
    proposed_filename: str
