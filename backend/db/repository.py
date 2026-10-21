"""
Data Access Layer (Repository).

Provides CRUD operations and specialized queries for image cataloging,
duplicate detection, category taxonomy, and operational logging.
"""

import itertools
import sqlite3
from typing import Optional, List, Dict, Any


def upsert_image(conn: sqlite3.Connection, data: Dict[str, Any]) -> int:
    """
    Inserts or updates an image record keyed by its unique source file_path.
    Returns the integer image id.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO images (
            file_path, file_name, file_size, file_hash_sha256, phash,
            width, height, file_format, date_taken, date_modified,
            thumbnail_path, status, primary_category_id, updated_at
        ) VALUES (
            :file_path, :file_name, :file_size, :file_hash_sha256, :phash,
            :width, :height, :file_format, :date_taken, :date_modified,
            :thumbnail_path, :status, :primary_category_id, DATETIME('now')
        )
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            file_size = excluded.file_size,
            file_hash_sha256 = excluded.file_hash_sha256,
            phash = excluded.phash,
            width = excluded.width,
            height = excluded.height,
            file_format = excluded.file_format,
            date_taken = excluded.date_taken,
            date_modified = excluded.date_modified,
            thumbnail_path = excluded.thumbnail_path,
            updated_at = DATETIME('now');
    """, data)
    
    if cursor.lastrowid and cursor.lastrowid > 0:
        return cursor.lastrowid
    
    # In case of update where lastrowid is not set
    cursor.execute("SELECT id FROM images WHERE file_path = ?", (data["file_path"],))
    row = cursor.fetchone()
    return row["id"] if row else 0


def get_image_by_id(conn: sqlite3.Connection, image_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single image by its primary key ID."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, c.display_name AS category_name, c.code_name AS category_code
        FROM images i
        LEFT JOIN categories c ON i.primary_category_id = c.id
        WHERE i.id = ?
    """, (image_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_image_by_path(conn: sqlite3.Connection, file_path: str) -> Optional[Dict[str, Any]]:
    """Fetches a single image by its absolute source path."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM images WHERE file_path = ?", (file_path,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_image_by_hash(conn: sqlite3.Connection, sha256_hash: str) -> Optional[Dict[str, Any]]:
    """Fetches an image with the given SHA-256 hash."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM images WHERE file_hash_sha256 = ? LIMIT 1", (sha256_hash,))
    row = cursor.fetchone()
    return dict(row) if row else None


def list_images(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    search_query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves a paginated list of images with optional filtering.
    """
    conditions = []
    params: List[Any] = []

    if category_id is not None:
        conditions.append("i.primary_category_id = ?")
        params.append(category_id)

    if status:
        conditions.append("i.status = ?")
        params.append(status)

    if search_query:
        conditions.append("(i.file_name LIKE ? OR i.file_path LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT 
            i.*,
            c.display_name AS category_name,
            c.code_name AS category_code
        FROM images i
        LEFT JOIN categories c ON i.primary_category_id = c.id
        {where_clause}
        ORDER BY i.date_taken DESC, i.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def count_images(
    conn: sqlite3.Connection,
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    search_query: Optional[str] = None
) -> int:
    """Returns the total number of images matching filter criteria."""
    conditions = []
    params: List[Any] = []

    if category_id is not None:
        conditions.append("primary_category_id = ?")
        params.append(category_id)

    if status:
        conditions.append("status = ?")
        params.append(status)

    if search_query:
        conditions.append("(file_name LIKE ? OR file_path LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT COUNT(*) AS total FROM images {where_clause}"

    cursor = conn.cursor()
    cursor.execute(query, params)
    row = cursor.fetchone()
    return row["total"] if row else 0


def get_categories(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieves all active categories."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY id ASC")
    return [dict(row) for row in cursor.fetchall()]


def get_category_by_id(conn: sqlite3.Connection, category_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single category by its ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_category_by_code(conn: sqlite3.Connection, code_name: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single category by its code_name."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories WHERE code_name = ?", (code_name,))
    row = cursor.fetchone()
    return dict(row) if row else None


def find_exact_duplicates(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Finds groups of images having the exact same SHA-256 hash.
    Returns list of duplicate hash groups and member file paths.
    Uses a single query with subquery filtering and itertools.groupby.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM images
        WHERE file_hash_sha256 IN (
            SELECT file_hash_sha256
            FROM images
            GROUP BY file_hash_sha256
            HAVING COUNT(*) > 1
        )
        ORDER BY file_hash_sha256, id ASC
    """)
    rows = [dict(row) for row in cursor.fetchall()]

    groups = []
    for h, items_iter in itertools.groupby(rows, key=lambda r: r["file_hash_sha256"]):
        members = list(items_iter)
        groups.append({
            "file_hash_sha256": h,
            "duplicate_count": len(members),
            "images": members,
        })

    return groups


def log_operation(
    conn: sqlite3.Connection,
    batch_id: str,
    operation_type: str,
    source_path: str,
    proposed_path: Optional[str] = None,
    destination_path: Optional[str] = None,
    image_id: Optional[int] = None,
    status: str = "proposed",
    error_message: Optional[str] = None
) -> int:
    """Records an entry in the operation_logs table."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO operation_logs (
            batch_id, operation_type, image_id, source_path,
            proposed_path, destination_path, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, operation_type, image_id, source_path, proposed_path, destination_path, status, error_message))
    return cursor.lastrowid or 0



def get_image_paths_under_directory(conn: sqlite3.Connection, directory_path: str) -> List[str]:
    """Returns all cataloged file_path values that reside within directory_path."""
    norm_dir_fwd = directory_path.rstrip("/\\") + "/"
    norm_dir_back = directory_path.rstrip("/\\") + "\\"
    cursor = conn.cursor()
    cursor.execute("""
        SELECT file_path FROM images
        WHERE file_path LIKE ? OR file_path LIKE ? OR file_path = ?
    """, (f"{norm_dir_fwd}%", f"{norm_dir_back}%", directory_path))
    return [row["file_path"] for row in cursor.fetchall()]


def update_image_status(conn: sqlite3.Connection, file_path: str, status: str) -> bool:
    """Updates the status of an image identified by its unique file_path."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE images SET status = ?, updated_at = DATETIME('now')
        WHERE file_path = ?
    """, (status, file_path))
    return cursor.rowcount > 0
