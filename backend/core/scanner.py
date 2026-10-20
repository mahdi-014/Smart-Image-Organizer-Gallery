"""
Recursive Directory Image Scanner.

Concepts Explained for Beginners:
1. Recursive Traversal:
   - Walks through a folder and all of its subfolders (no matter how deeply nested).
2. Pure Read-Only Guarantee:
   - Opens files exclusively with 'rb' (read binary) mode.
   - Never calls remove, move, or rename.
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
"""

import os
from pathlib import Path
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
    extensions: Set[str] = SUPPORTED_EXTENSIONS
) -> ScanProgress:
    """
    Recursively scans an image folder, extracts metadata, generates thumbnails,
    and inserts records into the SQLite catalog.
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
    candidates: List[Path] = []
    for root, dirs, files in os.walk(str(root_path), topdown=True, followlinks=False):
        # In-place directory pruning: os.walk only recurses into directories that remain in dirs
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_DIR_NAMES]

        for file_name in files:
            file_path = Path(root) / file_name
            if file_path.suffix.lower() in extensions:
                candidates.append(file_path)

    progress.total_found = len(candidates)
    if progress_callback:
        progress_callback(progress)

    # 2. Second pass: Process each image safely into SQLite
    with db_session(db_path) as conn:
        for file_path in candidates:
            progress.current_file = file_path.name
            try:
                # Cryptographic byte hash (SHA-256)
                sha256 = compute_sha256(file_path)
                # Perceptual hash deferred to Milestone 5
                phash = None
                # Metadata (dimensions, format, dates)
                meta = extract_metadata(file_path)
                # WebP thumbnail
                thumb_path = generate_thumbnail(file_path, sha256)

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
                    "status": "scanned",
                    "primary_category_id": None
                }

                repository.upsert_image(conn, record)
                progress.processed_count += 1

            except Exception as e:
                progress.error_count += 1
                progress.errors.append(f"Failed to process {file_path.name}: {str(e)}")

            if progress_callback:
                progress_callback(progress)

    progress.is_complete = True
    progress.current_file = ""
    if progress_callback:
        progress_callback(progress)

    return progress

