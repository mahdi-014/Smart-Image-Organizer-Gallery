"""
Folder Service: path validation, safety checks, directory overlap detection,
and Windows File Explorer integration.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("backend.core.folder_service")


def validate_local_folder(path_str: str, must_exist: bool = True) -> Path:
    """
    Validates that a folder path string is non-empty, absolute, points to a valid
    drive/filesystem location, and does not contain illegal traversal characters.

    If must_exist is True, the folder must currently exist and be a directory.
    If must_exist is False, the parent directory or root drive must be accessible.
    """
    if not path_str or not path_str.strip():
        raise ValueError("Folder path cannot be empty.")

    cleaned_str = path_str.strip().strip('"').strip("'")
    path = Path(cleaned_str)

    if not path.is_absolute():
        raise ValueError(f"Path must be an absolute path (e.g. C:\\Photos): {cleaned_str}")

    resolved = path.resolve()

    if must_exist:
        if not resolved.exists():
            raise ValueError(f"Directory does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {resolved}")
    else:
        # Destination folder: verify parent or root exists
        parent = resolved.parent
        if not parent.exists() and not resolved.drive:
            raise ValueError(f"Cannot create directory, parent does not exist: {parent}")

    return resolved


def check_folder_overlap(source_dir: Path, destination_dir: Path) -> bool:
    """
    Returns True if destination_dir is identical to source_dir or resides inside
    the source_dir hierarchy (which would cause recursive scanner loops).
    """
    src_resolved = source_dir.resolve()
    dest_resolved = destination_dir.resolve()

    if src_resolved == dest_resolved:
        return True

    try:
        # If dest is relative to src, it is inside the source folder
        dest_resolved.relative_to(src_resolved)
        return True
    except ValueError:
        return False


def browse_local_folder() -> Optional[str]:
    """
    Opens a native Windows folder browser dialog on the local machine.
    Returns the chosen folder path or None if cancelled.
    """
    try:
        # Prefer tkinter if available
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()  # Hide main root window
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select Folder")
        root.destroy()
        return folder if folder else None
    except Exception as e:
        logger.warning(f"tkinter folder dialog unavailable, attempting PowerShell fallback: {e}")
        try:
            ps_script = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$f.Description = 'Select Image Folder'; "
                "if($f.ShowDialog() -eq 'OK'){ Write-Output $f.SelectedPath }"
            )
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
            chosen = res.stdout.strip()
            return chosen if chosen else None
        except Exception as ps_err:
            logger.error(f"Failed to open native folder dialog: {ps_err}")
            return None


def open_in_file_explorer(folder_path: str) -> bool:
    """
    Opens the target folder in Windows File Explorer.
    """
    try:
        validated = validate_local_folder(folder_path, must_exist=False)
        if not validated.exists():
            validated.mkdir(parents=True, exist_ok=True)

        subprocess.Popen(["explorer.exe", str(validated)])
        return True
    except Exception as e:
        logger.error(f"Failed to open File Explorer for {folder_path}: {e}")
        return False


def clear_staging_catalog(db_path: Optional[Path] = None, clear_thumbnails: bool = True) -> int:
    """
    Clears all staged images from SQLite catalog and deletes cached preview thumbnails.
    """
    from backend.db.session import db_session
    from backend.db import repository
    from config.settings import settings

    with db_session(db_path) as conn:
        cleared_count = repository.clear_catalog_images(conn)

    if clear_thumbnails:
        thumb_dir = settings.thumbnails_dir
        if thumb_dir.exists():
            for f in thumb_dir.glob("*.webp"):
                try:
                    f.unlink()
                except Exception:
                    pass

    return cleared_count
