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


class ImageListResponse(BaseModel):
    """
    Paginated list response containing images and total catalog count.
    """
    items: List[ImageItemResponse]
    total: int
    limit: int
    offset: int
