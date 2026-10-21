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
    record = dict(data)
    record.setdefault("proposed_filename", None)
    record.setdefault("visual_description", None)

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO images (
            file_path, file_name, file_size, file_hash_sha256, phash,
            width, height, file_format, date_taken, date_modified,
            thumbnail_path, status, primary_category_id,
            proposed_filename, visual_description, updated_at
        ) VALUES (
            :file_path, :file_name, :file_size, :file_hash_sha256, :phash,
            :width, :height, :file_format, :date_taken, :date_modified,
            :thumbnail_path, :status, :primary_category_id,
            :proposed_filename, :visual_description, DATETIME('now')
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
            proposed_filename = COALESCE(images.proposed_filename, excluded.proposed_filename),
            visual_description = COALESCE(images.visual_description, excluded.visual_description),
            updated_at = DATETIME('now');
    """, record)

    if cursor.lastrowid and cursor.lastrowid > 0:
        return cursor.lastrowid

    # In case of update where lastrowid is not set
    cursor.execute("SELECT id FROM images WHERE file_path = ?", (record["file_path"],))
    row = cursor.fetchone()
    return row["id"] if row else 0


def update_image_semantic_metadata(
    conn: sqlite3.Connection,
    image_id: int,
    proposed_filename: Optional[str] = None,
    visual_description: Optional[str] = None,
) -> bool:
    """Updates the content-aware proposed filename and visual description for an image."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE images
        SET proposed_filename = COALESCE(?, proposed_filename),
            visual_description = COALESCE(?, visual_description),
            updated_at = DATETIME('now')
        WHERE id = ?
    """, (proposed_filename, visual_description, image_id))
    return cursor.rowcount > 0


def update_image_proposed_filename(
    conn: sqlite3.Connection,
    image_id: int,
    proposed_filename: str,
) -> bool:
    """Updates only the proposed filename for an image (e.g. from user manual review edit)."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE images
        SET proposed_filename = ?,
            updated_at = DATETIME('now')
        WHERE id = ?
    """, (proposed_filename, image_id))
    return cursor.rowcount > 0


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
    search_query: Optional[str] = None,
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
        conditions.append("(i.file_name LIKE ? OR i.file_path LIKE ? OR i.proposed_filename LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

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
    search_query: Optional[str] = None,
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
        conditions.append("(file_name LIKE ? OR file_path LIKE ? OR proposed_filename LIKE ?)")
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

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
    error_message: Optional[str] = None,
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


def override_image_category(
    conn: sqlite3.Connection,
    image_id: int,
    category_id: int,
    approve: bool = True,
) -> bool:
    """
    Updates the primary category of an image, optionally marking it approved,
    and marks any pending review queue items for this image as resolved.
    """
    cursor = conn.cursor()
    new_status = "approved" if approve else "classified"
    cursor.execute("""
        UPDATE images
        SET primary_category_id = ?, status = ?, updated_at = DATETIME('now')
        WHERE id = ?
    """, (category_id, new_status, image_id))
    image_updated = cursor.rowcount > 0

    # Resolve review queue entries
    cursor.execute("""
        UPDATE review_queue
        SET is_resolved = 1, resolved_category_id = ?, resolved_at = DATETIME('now')
        WHERE image_id = ? AND is_resolved = 0
    """, (category_id, image_id))

    return image_updated


def get_needs_review_images(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Returns list of images currently requiring manual user review."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            i.*,
            c.display_name AS category_name,
            c.code_name AS category_code,
            rq.reason AS review_reason
        FROM images i
        LEFT JOIN categories c ON i.primary_category_id = c.id
        LEFT JOIN review_queue rq ON i.id = rq.image_id AND rq.is_resolved = 0
        WHERE i.status = 'needs_review'
        ORDER BY i.id DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    return [dict(row) for row in cursor.fetchall()]


def clear_catalog_images(conn: sqlite3.Connection, image_ids: Optional[List[int]] = None) -> int:
    """
    Removes staged image records and related classifications/queue entries.
    If image_ids is provided, removes only specified images.
    Preserves operation_logs and category taxonomy.
    """
    cursor = conn.cursor()
    if image_ids:
        placeholders = ",".join(["?"] * len(image_ids))
        cursor.execute(f"DELETE FROM review_queue WHERE image_id IN ({placeholders})", image_ids)
        cursor.execute(f"DELETE FROM image_classifications WHERE image_id IN ({placeholders})", image_ids)
        cursor.execute(f"DELETE FROM image_tags WHERE image_id IN ({placeholders})", image_ids)
        cursor.execute(f"DELETE FROM images WHERE id IN ({placeholders})", image_ids)
        return cursor.rowcount
    else:
        cursor.execute("SELECT COUNT(*) FROM images")
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM review_queue")
        cursor.execute("DELETE FROM image_classifications")
        cursor.execute("DELETE FROM image_tags")
        cursor.execute("DELETE FROM images")
        return count
