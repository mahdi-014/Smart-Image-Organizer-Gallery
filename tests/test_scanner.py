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


def test_scan_directory_traversal_error_reporting(tmp_path: Path, temp_db: Path, monkeypatch):
    """
    Verifies that when a directory traversal error occurs (e.g. PermissionError):
    1. The onerror callback captures the error and increments error_count.
    2. An informative error message with the affected path is recorded in progress.errors.
    3. Other accessible directories and valid images continue to be processed.
    4. The database catalogs accessible images without interruption.
    """
    import os
    from PIL import Image

    # 1. Accessible directory with a valid image
    accessible_dir = tmp_path / "accessible"
    accessible_dir.mkdir()
    Image.new("RGB", (100, 100), "green").save(accessible_dir / "good.jpg")

    # 2. Locked directory (simulated PermissionError)
    locked_dir = tmp_path / "locked"
    locked_dir.mkdir()
    Image.new("RGB", (100, 100), "red").save(locked_dir / "unreachable.jpg")

    # Monkeypatch os.walk to trigger onerror when encountering 'locked'
    real_os_walk = os.walk

    def faulty_walk(top, topdown=True, onerror=None, followlinks=False):
        for root, dirs, files in real_os_walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
            if "locked" in dirs:
                dirs.remove("locked")
                if onerror is not None:
                    # Simulate PermissionError on the locked folder
                    simulated_err = PermissionError(13, "Access is denied", str(locked_dir))
                    onerror(simulated_err)
            yield root, dirs, files

    monkeypatch.setattr(os, "walk", faulty_walk)

    progress = scan_directory(str(tmp_path), db_path=temp_db)

    # Scan must complete gracefully
    assert progress.is_complete is True

    # Accessible image was discovered and cataloged
    assert progress.total_found == 1
    assert progress.processed_count == 1

    # Traversal error was captured and recorded
    assert progress.error_count == 1
    assert len(progress.errors) == 1
    error_msg = progress.errors[0]
    assert "Directory traversal error" in error_msg
    assert "locked" in error_msg
    assert "Access is denied" in error_msg

    # Database contains only the accessible image
    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 1
        images = repository.list_images(conn)
        assert images[0]["file_name"] == "good.jpg"


def test_scan_corrupt_image_rejection_and_mixed_scan(tmp_path: Path, temp_db: Path):
    """
    Verifies that when a folder contains both valid and corrupt image files:
    1. The corrupt file is rejected and excluded from the catalog.
    2. error_count is incremented and an informative error is recorded.
    3. The valid file is successfully cataloged.
    4. processed_count only counts successfully cataloged images.
    """
    from PIL import Image

    # 1. Valid image
    valid_file = tmp_path / "valid_landscape.png"
    Image.new("RGB", (200, 200), "green").save(valid_file)

    # 2. Corrupt image file (supported extension, invalid byte contents)
    corrupt_file = tmp_path / "broken_image.jpg"
    corrupt_file.write_bytes(b"corrupt junk data that cannot be parsed as jpeg")

    progress = scan_directory(str(tmp_path), db_path=temp_db)

    assert progress.is_complete is True
    assert progress.total_found == 2
    assert progress.processed_count == 1
    assert progress.error_count == 1

    assert len(progress.errors) == 1
    assert "broken_image.jpg" in progress.errors[0]

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 1
        images = repository.list_images(conn)
        assert images[0]["file_name"] == "valid_landscape.png"


def test_scan_thumbnail_failure_rejects_catalog_record(tmp_path: Path, temp_db: Path, monkeypatch):
    """
    Verifies that if thumbnail generation fails (returns None):
    1. The image is NOT inserted into the database.
    2. processed_count is NOT incremented.
    3. error_count is incremented once with an informative message.
    """
    from PIL import Image
    import backend.core.scanner as scanner_module

    # Valid image on disk
    valid_file = tmp_path / "photo_needs_thumb.jpg"
    Image.new("RGB", (150, 150), "yellow").save(valid_file)

    # Monkeypatch generate_thumbnail in scanner to return None
    monkeypatch.setattr(scanner_module, "generate_thumbnail", lambda *args, **kwargs: None)

    progress = scan_directory(str(tmp_path), db_path=temp_db)

    assert progress.is_complete is True
    assert progress.total_found == 1
    assert progress.processed_count == 0
    assert progress.error_count == 1
    assert len(progress.errors) == 1
    assert "Failed to generate thumbnail for photo_needs_thumb.jpg" in progress.errors[0]

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 0







def test_scan_transaction_batching_crash_resilience(tmp_path: Path, temp_db: Path, monkeypatch):
    """
    Verifies that:
    1. The scanner commits every 200 images (or batch_size images).
    2. A fatal error/crash mid-scan preserves previously committed batches in the database.
    """
    import pytest
    from PIL import Image
    import backend.core.scanner as scanner_module

    # Create 220 lightweight test images
    img_dir = tmp_path / "batch_images"
    img_dir.mkdir()
    for i in range(1, 221):
        Image.new("RGB", (10, 10), "blue").save(img_dir / f"img_{i:04d}.jpg")

    # Simulate a crash/fatal unhandled exception at image 210
    original_upsert = scanner_module.repository.upsert_image
    call_count = [0]

    def crash_upsert(conn, record):
        call_count[0] += 1
        if call_count[0] == 210:
            raise KeyboardInterrupt("Simulated sudden crash / power outage mid-scan")
        return original_upsert(conn, record)

    monkeypatch.setattr(scanner_module.repository, "upsert_image", crash_upsert)

    with pytest.raises(KeyboardInterrupt):
        scan_directory(str(img_dir), db_path=temp_db, batch_size=200)

    # Images 1-200 were committed in batch 1 and MUST persist on disk!
    with db_session(temp_db) as conn:
        committed_count = repository.count_images(conn)
        assert committed_count == 200


def test_incremental_scan_skips_unchanged_images(tmp_path: Path, temp_db: Path, monkeypatch):
    """
    Verifies that:
    1. Initial scan catalogs all images.
    2. Re-scanning an unchanged directory skips hashing and metadata extraction.
    3. Zero new rows are created in the database.
    4. progress.skipped_count equals total images.
    """
    from PIL import Image
    import backend.core.scanner as scanner_module

    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    for i in range(1, 6):
        Image.new("RGB", (50, 50), "green").save(img_dir / f"pic_{i}.jpg")

    # Pass 1: Initial scan
    p1 = scan_directory(str(img_dir), db_path=temp_db)
    assert p1.processed_count == 5
    assert p1.skipped_count == 0

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 5

    # Monkeypatch compute_sha256 and extract_metadata so that if they are called, test fails!
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Expensive hashing / extraction was called on an unchanged file!")

    monkeypatch.setattr(scanner_module, "compute_sha256", fail_if_called)
    monkeypatch.setattr(scanner_module, "extract_metadata", fail_if_called)

    # Pass 2: Re-scan unchanged directory
    p2 = scan_directory(str(img_dir), db_path=temp_db)
    assert p2.is_complete is True
    assert p2.total_found == 5
    assert p2.skipped_count == 5
    assert p2.processed_count == 0
    assert p2.error_count == 0

    # Ensure zero new rows created
    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 5


def test_incremental_scan_detects_mtime_or_size_change(tmp_path: Path, temp_db: Path):
    """
    Verifies that if an image's content or mtime changes on disk,
    it is NOT skipped: it is re-hashed, re-extracted, and updated.
    """
    import time
    from PIL import Image

    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    file_a = img_dir / "photo_a.jpg"
    file_b = img_dir / "photo_b.jpg"

    Image.new("RGB", (50, 50), "red").save(file_a)
    Image.new("RGB", (50, 50), "blue").save(file_b)

    # Pass 1: Initial scan
    p1 = scan_directory(str(img_dir), db_path=temp_db)
    assert p1.processed_count == 2
    assert p1.skipped_count == 0

    with db_session(temp_db) as conn:
        rec_a1 = repository.get_image_by_path(conn, str(file_a.resolve()))
        hash_a1 = rec_a1["file_hash_sha256"]

    # Modify file_a (change pixels so size/mtime/hash changes)
    time.sleep(0.05)  # Ensure mtime timestamp difference
    Image.new("RGB", (100, 100), "yellow").save(file_a)

    # Pass 2: Re-scan
    p2 = scan_directory(str(img_dir), db_path=temp_db)
    assert p2.total_found == 2
    assert p2.skipped_count == 1   # file_b was unchanged and skipped
    assert p2.processed_count == 1 # file_a was modified and re-processed
    assert p2.error_count == 0

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 2  # Still 2 images, zero duplicate rows
        rec_a2 = repository.get_image_by_path(conn, str(file_a.resolve()))
        assert rec_a2["file_hash_sha256"] != hash_a1
        assert rec_a2["width"] == 100


def test_scan_detects_and_reports_deleted_or_moved_files(tmp_path: Path, temp_db: Path):
    """
    Verifies that files deleted or moved since the last scan are detected,
    reported in progress.missing_files, marked in DB, and no source files are touched.
    """
    from PIL import Image

    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    f1 = img_dir / "keep.jpg"
    f2 = img_dir / "will_delete.jpg"

    Image.new("RGB", (50, 50), "cyan").save(f1)
    Image.new("RGB", (50, 50), "magenta").save(f2)

    # Pass 1: Initial scan
    p1 = scan_directory(str(img_dir), db_path=temp_db)
    assert p1.processed_count == 2

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 2

    # Delete f2 from disk
    f2.unlink()
    assert not f2.exists()

    # Pass 2: Re-scan
    p2 = scan_directory(str(img_dir), db_path=temp_db)
    assert p2.total_found == 1
    assert p2.skipped_count == 1 # f1 was skipped
    assert hasattr(p2, "missing_files")
    assert len(p2.missing_files) == 1
    assert "will_delete.jpg" in p2.missing_files[0]
    assert p2.missing_count == 1

    # In DB, verify f2 status was marked 'needs_review'
    with db_session(temp_db) as conn:
        rec_f2 = repository.get_image_by_path(conn, str(f2.resolve()))
        assert rec_f2 is not None
        assert rec_f2["status"] == "needs_review"
