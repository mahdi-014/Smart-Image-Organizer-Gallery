"""
API dependencies and database connection lifecycle management.
"""

import sqlite3
from pathlib import Path
from typing import Generator, Optional
from fastapi import HTTPException, status

from config.settings import settings
from backend.db.session import db_session

_db_path_override: Optional[Path] = None


def set_db_path_override(db_path: Optional[Path]) -> None:
    global _db_path_override
    _db_path_override = db_path


def get_db_path() -> Path:
    return _db_path_override or settings.database_path


def open_read_only_connection(db_path: Path) -> sqlite3.Connection:
    """
    Open an existing SQLite catalog in read-only mode using a URI.

    Verifies that the target file exists and that the required images
    table has been created. Raises a controlled HTTP 503 if the database
    is missing, uninitialized, or inaccessible.
    """
    if not db_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database catalog is not initialized or unavailable.",
        )

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.OperationalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database catalog is unavailable.",
        )

    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='images';"
        )
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database catalog schema is not initialized.",
            )
    except sqlite3.OperationalError:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database catalog schema is not initialized.",
        )

    return conn


def get_read_only_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency yielding a read-only SQLite database connection
    for the application's configured database catalog.
    """
    conn = open_read_only_connection(get_db_path())
    try:
        yield conn
    finally:
        conn.close()


def get_write_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency yielding a writable SQLite transaction session.
    """
    with db_session(get_db_path()) as conn:
        yield conn


def validate_thumbnail_path(
    raw_path: Optional[str],
    allowed_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Validates that raw_path resolves to an existing file strictly located
    inside the allowed thumbnail directory.

    Guards against:
    - Null / empty paths
    - Path traversal attacks (e.g. ../..)
    - Paths pointing outside the allowed thumbnails directory
    - Symlink escapes pointing outside the thumbnails directory
    - Non-existent files or directories

    Returns:
        The canonical, resolved Path if valid and safe, or None if invalid.
    """
    if not raw_path or not isinstance(raw_path, str) or not raw_path.strip():
        return None

    path_obj = Path(raw_path.strip())
    target_dir = allowed_dir or settings.thumbnails_dir

    if path_obj.is_absolute():
        candidate = path_obj
    else:
        candidate_project = settings.project_root / path_obj
        if candidate_project.exists():
            candidate = candidate_project
        else:
            candidate = target_dir / path_obj

    try:
        resolved_file = candidate.resolve()
        resolved_allowed_dir = target_dir.resolve()

        # Defend against target being the directory itself
        if resolved_file == resolved_allowed_dir:
            return None

        # Defend against traversal and symlink escapes
        if not resolved_file.is_relative_to(resolved_allowed_dir):
            return None

        # Must be an existing regular file
        if not resolved_file.is_file():
            return None

        return resolved_file
    except (ValueError, OSError, RuntimeError):
        return None
