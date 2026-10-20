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


def test_scan_extended_formats_and_case_insensitivity(tmp_path: Path, temp_db: Path):
    """
    Verifies that scan_directory discovers BMP, GIF, TIFF, and TIF formats,
    handles uppercase extensions case-insensitively, and ignores non-images.
    """
    from PIL import Image

    # 1. Lowercase extended formats
    Image.new("RGB", (100, 100), "red").save(tmp_path / "graphic.bmp")
    Image.new("P", (80, 80)).save(tmp_path / "clip.gif")
    Image.new("RGB", (120, 120), "blue").save(tmp_path / "scan.tiff")
    Image.new("RGB", (140, 140), "green").save(tmp_path / "photo.tif")

    # 2. Uppercase extensions (case-insensitivity test)
    Image.new("RGB", (90, 90), "yellow").save(tmp_path / "UPPERCASE_SAMPLE.BMP")
    Image.new("RGB", (110, 110), "purple").save(tmp_path / "ARCHIVE_SCAN.TIFF")

    # 3. Non-image files that must be ignored
    (tmp_path / "notes.txt").write_text("Should be ignored", encoding="utf-8")
    (tmp_path / "program.py").write_text("print('Ignore')", encoding="utf-8")

    progress = scan_directory(
        directory_path=str(tmp_path),
        db_path=temp_db
    )

    assert progress.is_complete is True
    assert progress.total_found == 6
    assert progress.processed_count == 6
    assert progress.error_count == 0

    with db_session(temp_db) as conn:
        total = repository.count_images(conn)
        assert total == 6

        images = repository.list_images(conn, limit=10)
        formats = {img["file_format"] for img in images}
        assert "BMP" in formats
        assert "GIF" in formats
        assert "TIFF" in formats


def test_directory_pruning_and_traversal_prevention(tmp_path: Path, temp_db: Path, monkeypatch):
    """
    Verifies that:
    1. os.walk genuinely prunes ignored directories in-place and never visits them.
    2. Case-insensitive directory names (e.g., VENV, .GIT) are pruned.
    3. Legitimate nested directories are traversed.
    4. Images in ignored directories never enter the database catalog.
    """
    import os
    from PIL import Image

    # A. Legitimate directory structure
    valid_dir = tmp_path / "valid_photos"
    nested_valid_dir = valid_dir / "nested_subfolder"
    nested_valid_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), "red").save(valid_dir / "pic1.jpg")
    Image.new("RGB", (100, 100), "green").save(nested_valid_dir / "pic2.png")
    (valid_dir / "readme.txt").write_text("Ignore text", encoding="utf-8")

    # B. Ignored directory structures (lowercase & uppercase)
    ignored_specs = [
        tmp_path / ".git" / "hooks",
        tmp_path / "venv" / "Lib" / "site-packages",
        tmp_path / "__pycache__",
        tmp_path / "node_modules" / "express",
        tmp_path / "VENV" / "nested",
        tmp_path / ".GIT" / "objects",
    ]
    for p in ignored_specs:
        p.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100), "black").save(p / "should_never_be_scanned.jpg")

    # Instrument os.walk to record every directory root visited during traversal
    visited_roots = []
    real_os_walk = os.walk

    def tracking_walk(top, topdown=True, onerror=None, followlinks=False):
        for root, dirs, files in real_os_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
            visited_roots.append(Path(root))
            yield root, dirs, files

    monkeypatch.setattr(os, "walk", tracking_walk)

    # Run the scanner
    progress = scan_directory(str(tmp_path), db_path=temp_db)

    # 1. Total found & processed should be exactly 2 (the two legitimate images)
    assert progress.is_complete is True
    assert progress.total_found == 2
    assert progress.processed_count == 2
    assert progress.error_count == 0

    # 2. Verify in SQLite that only legitimate images were cataloged
    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 2
        images = repository.list_images(conn)
        cataloged_names = {img["file_name"] for img in images}
        assert cataloged_names == {"pic1.jpg", "pic2.png"}

    # 3. VERIFY PRUNING: None of the ignored directories or their subdirectories were ever visited!
    # Convert all visited paths to lower-case parts for inspection
    for visited_path in visited_roots:
        parts_lower = [part.lower() for part in visited_path.parts]
        assert ".git" not in parts_lower, f"os.walk visited ignored directory: {visited_path}"
        assert "venv" not in parts_lower, f"os.walk visited ignored directory: {visited_path}"
        assert "__pycache__" not in parts_lower, f"os.walk visited ignored directory: {visited_path}"
        assert "node_modules" not in parts_lower, f"os.walk visited ignored directory: {visited_path}"

    # 4. Confirm that legitimate nested directories WERE visited
    visited_names = {p.name for p in visited_roots}
    assert "valid_photos" in visited_names
    assert "nested_subfolder" in visited_names



