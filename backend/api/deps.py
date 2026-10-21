"""
API dependencies and database connection lifecycle management.
"""

import sqlite3
from pathlib import Path
from typing import Generator
from fastapi import HTTPException, status

from config.settings import settings


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
    conn = open_read_only_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()
