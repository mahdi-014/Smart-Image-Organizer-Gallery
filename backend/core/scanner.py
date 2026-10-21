"""
Recursive Directory Image Scanner.

Concepts Explained for Beginners:
1. Recursive Traversal:
   - Walks through a folder and all of its subfolders (no matter how deeply nested).
2. Pure Read-Only Guarantee:
   - Opens files exclusively with 'rb' (read binary) mode.
   - Never calls remove, move, or rename on source files.
3. Path Normalization:
   - Resolves relative paths into absolute canonical Windows paths so the database
     always holds unambiguous references.
4. Progress Reporting:
   - Dispatches callbacks with live counts (processed, errors, skipped) so web UI
     can show real-time progress bars.
5. Top-Down Traversal with Directory Pruning:
   - Uses os.walk(topdown=True) and modifies dirnames in-place (dirs[:] = [...]).
   - This prevents os.walk from ever descending into ignored folders like .git, venv,
     or node_modules, saving thousands of disk operations on large collections.
6. Traversal Error Handling:
   - Uses os.walk(onerror=...) to capture filesystem errors (such as PermissionError
     or inaccessible directories) so they are reported rather than silently skipped.
7. Incremental Scanning:
   - Skips expensive SHA-256 hashing and EXIF extraction if a file's path, size,
     and modification timestamp (mtime) match an existing catalog record.
8. Transaction Batching:
   - Commits records in batches of 200 to keep memory low, avoid long database write locks,
     and guarantee progress preservation if a scan is interrupted.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List, Set
from pydantic import BaseModel

from config.settings import settings, SUPPORTED_EXTENSIONS
from backend.core.hasher import compute_sha256
from backend.core.metadata import extract_metadata, generate_thumbnail
from backend.db.session import db_session
from backend.db import repository


class ScanProgress(BaseModel):
    """Snapshot of scanning progress for UI reporting."""
    total_found: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    missing_count: int = 0
    missing_files: List[str] = []
    current_file: str = ""
    is_complete: bool = False
    errors: List[str] = []


# Directories to always skip if encountered during traversal
IGNORED_DIR_NAMES: Set[str] = {
    "venv", ".git", ".idea", ".vscode", "__pycache__",
    "node_modules", ".cache", "thumbnails", "$recycle.bin",
    "system volume information"
}


def scan_directory(
    directory_path: str,
    progress_callback: Optional[Callable[[ScanProgress], None]] = None,
    db_path: Optional[Path] = None,
    extensions: Set[str] = SUPPORTED_EXTENSIONS,
    batch_size: int = 200
) -> ScanProgress:
    """
    Recursively scans an image folder, extracts metadata, generates thumbnails,
    and inserts records into the SQLite catalog using incremental caching
    and transaction batching.
    """
    root_path = Path(directory_path).resolve()
    progress = ScanProgress()

    if not root_path.exists() or not root_path.is_dir():
        progress.errors.append(f"Directory does not exist or is not a folder: {root_path}")
        progress.is_complete = True
        if progress_callback:
            progress_callback(progress)
        return progress

    # 1. First pass: Collect all candidates matching image extensions using pruned top-down traversal
    def on_walk_error(err: OSError) -> None:
        progress.error_count += 1
        err_path = getattr(err, "filename", None) or str(root_path)
        err_msg = err.strerror or str(err)
        progress.errors.append(f"Directory traversal error accessing '{err_path}': {err_msg}")
        if progress_callback:
            progress_callback(progress)

    candidates: List[Path] = []
    for root, dirs, files in os.walk(str(root_path), topdown=True, onerror=on_walk_error, followlinks=False):
        # In-place directory pruning: os.walk only recurses into directories that remain in dirs
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIR_NAMES]

        for file_name in files:
            file_path = Path(root) / file_name
            if file_path.suffix.lower() in extensions:
                candidates.append(file_path)

    progress.total_found = len(candidates)
    if progress_callback:
        progress_callback(progress)

    # 2. Second pass: Process each image into SQLite with incremental check and transaction batching
    candidate_paths_set: Set[str] = {str(p.resolve()) for p in candidates}

    with db_session(db_path) as conn:
        # Check for missing / moved files previously indexed under this directory
        existing_paths = repository.get_image_paths_under_directory(conn, str(root_path))
        for p_str in existing_paths:
            if p_str not in candidate_paths_set or not Path(p_str).exists():
                progress.missing_count += 1
                progress.missing_files.append(p_str)
                repository.update_image_status(conn, p_str, "needs_review")

        if progress.missing_count > 0:
            conn.commit()

        uncommitted_count = 0

        for file_path in candidates:
            canonical_path = str(file_path.resolve())
            progress.current_file = file_path.name

            try:
                # Fast stat check for incremental skip
                stat = file_path.stat()
                current_size = stat.st_size
                current_mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()

                existing = repository.get_image_by_path(conn, canonical_path)
                if (
                    existing is not None
                    and existing.get("file_size") == current_size
                    and existing.get("date_modified") == current_mtime
                    and existing.get("file_hash_sha256")
                    and existing.get("thumbnail_path")
                ):
                    # Verify thumbnail exists on disk
                    thumb_candidate = Path(existing["thumbnail_path"])
                    thumb_full = (
                        thumb_candidate
                        if thumb_candidate.is_absolute()
                        else (settings.project_root / thumb_candidate)
                    )
                    if thumb_full.exists():
                        progress.skipped_count += 1
                        if progress_callback:
                            progress_callback(progress)
                        continue

                # File is new or modified: compute hash, extract metadata, generate thumbnail
                sha256 = compute_sha256(file_path)
                phash = None
                meta = extract_metadata(file_path)

                thumb_path = generate_thumbnail(file_path, sha256)
                if not thumb_path:
                    raise RuntimeError(f"Failed to generate thumbnail for {file_path.name}")

                record: Dict[str, Any] = {
                    "file_path": meta["file_path"],
                    "file_name": meta["file_name"],
                    "file_size": meta["file_size"],
                    "file_hash_sha256": sha256,
                    "phash": phash,
                    "width": meta["width"],
                    "height": meta["height"],
                    "file_format": meta["file_format"],
                    "date_taken": meta["date_taken"],
                    "date_modified": meta["date_modified"],
                    "thumbnail_path": thumb_path,
                    "status": existing["status"] if existing and existing.get("status") else "scanned",
                    "primary_category_id": existing["primary_category_id"] if existing else None
                }

                repository.upsert_image(conn, record)
                progress.processed_count += 1
                uncommitted_count += 1

                # Transaction batching checkpoint
                if uncommitted_count >= batch_size:
                    conn.commit()
                    uncommitted_count = 0

            except FileNotFoundError as fnf_err:
                # Confirm whether the source image itself has actually disappeared
                if not file_path.exists():
                    if canonical_path not in progress.missing_files:
                        progress.missing_count += 1
                        progress.missing_files.append(canonical_path)
                    existing = repository.get_image_by_path(conn, canonical_path)
                    if existing is not None and existing.get("status") != "needs_review":
                        repository.update_image_status(conn, canonical_path, "needs_review")
                        uncommitted_count += 1
                else:
                    # Source image exists; FileNotFoundError was caused by an internal asset / dependency
                    progress.error_count += 1
                    progress.errors.append(f"Failed to process {file_path.name}: {str(fnf_err)}")
            except Exception as e:
                progress.error_count += 1
                progress.errors.append(f"Failed to process {file_path.name}: {str(e)}")

            if progress_callback:
                progress_callback(progress)

        # Commit any remaining records
        if uncommitted_count > 0:
            conn.commit()
            uncommitted_count = 0

    progress.is_complete = True
    progress.current_file = ""
    if progress_callback:
        progress_callback(progress)

    return progress
