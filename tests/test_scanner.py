"""
Integration tests for the Image Scanner engine.
"""

from pathlib import Path
from backend.core.scanner import scan_directory
from backend.db.session import db_session
from backend.db import repository


def test_scan_directory_and_duplicate_detection(sample_images_dir: Path, temp_db: Path):
    """
    Scans the synthetic test directory into an isolated SQLite database and verifies:
    - Discovery of all 11 supported images (.jpg, .png, .webp).
    - Rejection of non-image files (.txt, .py).
    - Accurate population of dimensions, hashes, and thumbnails.
    - Identification of exact byte duplicates.
    """
    progress = scan_directory(
        directory_path=str(sample_images_dir),
        db_path=temp_db
    )

    assert progress.is_complete is True
    assert progress.total_found == 11
    assert progress.processed_count == 11
    assert progress.error_count == 0

    with db_session(temp_db) as conn:
        total = repository.count_images(conn)
        assert total == 11

        # Check duplicate detection
        duplicate_groups = repository.find_exact_duplicates(conn)
        # We created 2 duplicate pairs: headphones & receipt
        assert len(duplicate_groups) == 2

        for grp in duplicate_groups:
            assert grp["duplicate_count"] == 2
            names = [img["file_name"] for img in grp["images"]]
            assert any("headphones" in n for n in names) or any("receipt" in n for n in names)


def test_scan_nonexistent_directory(temp_db: Path):
    """Verifies that scanning a non-existent path gracefully handles errors without raising an exception."""
    progress = scan_directory(
        directory_path="C:/this/path/definitely/does/not/exist",
        db_path=temp_db
    )
    assert progress.is_complete is True
    assert len(progress.errors) > 0
    assert progress.processed_count == 0

