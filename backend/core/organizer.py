"""
Safe File Organizer Engine.

Performs dry-run folder structure generation, filename collision resolution,
byte-for-byte file copies via shutil.copy2, SHA-256 copy verification,
and audit logging in SQLite operation_logs.
Original source files are NEVER modified, moved, renamed, or deleted.
"""

import os
import uuid
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from pydantic import BaseModel, Field

from backend.db.session import db_session
from backend.db import repository
from backend.core.hasher import compute_sha256

logger = logging.getLogger("backend.core.organizer")


class OrganizationPlanItem(BaseModel):
    image_id: int
    source_path: str
    destination_path: str
    destination_filename: str
    category_name: str
    subcategory: Optional[str] = None
    file_size: int
    source_hash: str
    collision_detected: bool = False


class OrganizationPlan(BaseModel):
    batch_id: str
    destination_root: str
    total_files: int
    total_bytes: int
    categories_summary: Dict[str, int]
    items: List[OrganizationPlanItem]


class OrganizationResult(BaseModel):
    batch_id: str
    total_files: int
    copied_count: int
    verified_count: int
    failed_count: int
    destination_root: str
    errors: List[str] = Field(default_factory=list)


def _sanitize_folder_name(name: str) -> str:
    """Replaces invalid Windows path characters with underscores."""
    invalid_chars = '<>:"/\\|?*'
    sanitized = "".join(c if c not in invalid_chars else "_" for c in name)
    return sanitized.strip().strip(".") or "Uncategorized"


def generate_organization_plan(
    destination_dir: str,
    db_path: Optional[Path] = None,
    image_ids: Optional[List[int]] = None,
    include_needs_review: bool = False,
) -> OrganizationPlan:
    """
    Generates a dry-run organization plan without touching the filesystem.
    Calculates target paths, resolves collisions, and returns a detailed manifest.
    """
    batch_id = str(uuid.uuid4())
    dest_root = Path(destination_dir).resolve()

    items: List[OrganizationPlanItem] = []
    total_bytes = 0
    categories_summary: Dict[str, int] = {}
    assigned_dest_paths: Set[str] = set()

    with db_session(db_path) as conn:
        cursor = conn.cursor()

        if image_ids:
            placeholders = ",".join(["?"] * len(image_ids))
            cursor.execute(
                f"""
                SELECT i.*, c.display_name AS category_display_name
                FROM images i
                LEFT JOIN categories c ON i.primary_category_id = c.id
                WHERE i.id IN ({placeholders})
                ORDER BY i.id ASC
                """,
                image_ids,
            )
        else:
            status_filter = "('classified', 'approved', 'needs_review')" if include_needs_review else "('classified', 'approved')"
            cursor.execute(
                f"""
                SELECT i.*, c.display_name AS category_display_name
                FROM images i
                LEFT JOIN categories c ON i.primary_category_id = c.id
                WHERE i.status IN {status_filter}
                ORDER BY i.id ASC
                """
            )

        rows = [dict(r) for r in cursor.fetchall()]

        for row in rows:
            src_path = Path(row["file_path"])
            cat_display = row.get("category_display_name") or "Needs Review"
            sanitized_cat = _sanitize_folder_name(cat_display)

            # Subcategory if present in classifications or tags
            subcategory = None
            cursor.execute(
                "SELECT suggested_tags_json FROM image_classifications WHERE image_id = ? ORDER BY id DESC LIMIT 1",
                (row["id"],),
            )
            cls_row = cursor.fetchone()
            if cls_row and cls_row["suggested_tags_json"]:
                try:
                    import json
                    tags = json.loads(cls_row["suggested_tags_json"])
                    if len(tags) > 1:
                        subcategory = _sanitize_folder_name(tags[1])
                except Exception:
                    pass

            # Target directory
            if subcategory and subcategory.lower() not in ("general", "uncategorized"):
                target_dir = dest_root / sanitized_cat / subcategory
            else:
                target_dir = dest_root / sanitized_cat

            original_name = src_path.name
            stem = src_path.stem
            suffix = src_path.suffix

            candidate_dest = target_dir / original_name
            candidate_str = str(candidate_dest.resolve())

            # Collision resolution: check assigned set AND disk
            collision_detected = False
            counter = 1
            while candidate_str in assigned_dest_paths or (dest_root.exists() and candidate_dest.exists()):
                collision_detected = True
                counter += 1
                candidate_dest = target_dir / f"{stem} ({counter}){suffix}"
                candidate_str = str(candidate_dest.resolve())

            assigned_dest_paths.add(candidate_str)

            file_size = row.get("file_size") or 0
            total_bytes += file_size
            categories_summary[sanitized_cat] = categories_summary.get(sanitized_cat, 0) + 1

            items.append(
                OrganizationPlanItem(
                    image_id=row["id"],
                    source_path=str(src_path),
                    destination_path=candidate_str,
                    destination_filename=candidate_dest.name,
                    category_name=sanitized_cat,
                    subcategory=subcategory,
                    file_size=file_size,
                    source_hash=row["file_hash_sha256"],
                    collision_detected=collision_detected,
                )
            )

    return OrganizationPlan(
        batch_id=batch_id,
        destination_root=str(dest_root),
        total_files=len(items),
        total_bytes=total_bytes,
        categories_summary=categories_summary,
        items=items,
    )


def execute_organization_plan(
    plan: OrganizationPlan,
    db_path: Optional[Path] = None,
) -> OrganizationResult:
    """
    Executes an approved organization plan:
    1. Creates target category folders.
    2. Copies original files with shutil.copy2 (source files are never altered).
    3. Re-computes SHA-256 on destination files and validates equality.
    4. Logs all operations in SQLite operation_logs.
    5. Updates catalog image records to status='organized'.
    """
    batch_id = plan.batch_id
    copied_count = 0
    verified_count = 0
    failed_count = 0
    errors: List[str] = []

    with db_session(db_path) as conn:
        for item in plan.items:
            src_path = Path(item.source_path)
            dest_path = Path(item.destination_path)

            if not src_path.exists():
                err = f"Source file no longer exists: {src_path}"
                logger.error(err)
                errors.append(err)
                failed_count += 1
                repository.log_operation(
                    conn,
                    batch_id=batch_id,
                    operation_type="copy_rename",
                    source_path=str(src_path),
                    destination_path=str(dest_path),
                    image_id=item.image_id,
                    status="failed",
                    error_message=err,
                )
                continue

            try:
                # 1. Ensure target directory exists
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # 2. Log in_progress
                repository.log_operation(
                    conn,
                    batch_id=batch_id,
                    operation_type="copy_rename",
                    source_path=str(src_path),
                    destination_path=str(dest_path),
                    image_id=item.image_id,
                    status="in_progress",
                )

                # 3. Copy byte-for-byte with shutil.copy2
                shutil.copy2(src_path, dest_path)
                copied_count += 1

                # 4. Cryptographic SHA-256 verification
                dest_hash = compute_sha256(dest_path)
                if dest_hash != item.source_hash:
                    # Hash mismatch! Remove corrupt destination copy
                    if dest_path.exists():
                        dest_path.unlink()
                    err = f"SHA-256 mismatch for {src_path.name}: expected {item.source_hash}, got {dest_hash}"
                    logger.error(err)
                    errors.append(err)
                    failed_count += 1
                    repository.log_operation(
                        conn,
                        batch_id=batch_id,
                        operation_type="copy_rename",
                        source_path=str(src_path),
                        destination_path=str(dest_path),
                        image_id=item.image_id,
                        status="failed",
                        error_message=err,
                    )
                    continue

                # 5. Success: mark completed
                verified_count += 1
                repository.log_operation(
                    conn,
                    batch_id=batch_id,
                    operation_type="copy_rename",
                    source_path=str(src_path),
                    destination_path=str(dest_path),
                    image_id=item.image_id,
                    status="completed",
                )

                # Update database catalog image status
                repository.update_image_status(conn, str(src_path), "organized")

            except Exception as e:
                err = f"Failed copying {src_path} -> {dest_path}: {e}"
                logger.error(err)
                errors.append(err)
                failed_count += 1
                # If partial file written, remove it
                if dest_path.exists():
                    try:
                        dest_path.unlink()
                    except Exception:
                        pass
                repository.log_operation(
                    conn,
                    batch_id=batch_id,
                    operation_type="copy_rename",
                    source_path=str(src_path),
                    destination_path=str(dest_path),
                    image_id=item.image_id,
                    status="failed",
                    error_message=err,
                )

    return OrganizationResult(
        batch_id=batch_id,
        total_files=plan.total_files,
        copied_count=copied_count,
        verified_count=verified_count,
        failed_count=failed_count,
        destination_root=plan.destination_root,
        errors=errors,
    )
