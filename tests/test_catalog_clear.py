"""
Tests for Catalog Staging Clearing and Auto-Removal of Organized Images.
"""

from pathlib import Path
import pytest
from PIL import Image

from backend.db.session import init_db, db_session
from backend.db import repository
from backend.core.hasher import compute_sha256
from backend.core.organizer import generate_organization_plan, execute_organization_plan
from backend.core.folder_service import clear_staging_catalog


def test_clear_staging_catalog_removes_images_and_thumbnails(tmp_path: Path, temp_db: Path):
    """Verifies clear_staging_catalog purges staged records and thumbnails while preserving audit logs."""
    src_file = tmp_path / "test.jpg"
    Image.new("RGB", (50, 50), "red").save(src_file)

    thumb_file = tmp_path / "thumb_test.webp"
    Image.new("RGB", (30, 30), "red").save(thumb_file)

    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": str(src_file),
            "file_name": "test.jpg",
            "file_size": 100,
            "file_hash_sha256": "hash_clear_test",
            "phash": "dummy",
            "width": 50,
            "height": 50,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": str(thumb_file),
            "status": "scanned",
            "primary_category_id": None,
        })
        # Log an operation
        repository.log_operation(
            conn,
            batch_id="batch_1",
            operation_type="scan",
            source_path=str(src_file),
            image_id=img_id,
            status="completed",
        )
        assert repository.count_images(conn) == 1

    # Perform clearing
    cleared = clear_staging_catalog(db_path=temp_db, clear_thumbnails=True)
    assert cleared == 1

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 0
        # Audit log preserved
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM operation_logs")
        assert cursor.fetchone()[0] == 1


def test_execute_organization_plan_auto_removes_organized_files(tmp_path: Path, temp_db: Path):
    """Verifies that organized files are automatically cleared from staging catalog once verified."""
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    dest_dir = tmp_path / "destination"

    img_file = src_dir / "sunset.jpg"
    Image.new("RGB", (80, 80), "blue").save(img_file)
    src_hash = compute_sha256(img_file)

    with db_session(temp_db) as conn:
        cats = repository.get_categories(conn)
        cat_id = cats[0]["id"]
        img_id = repository.upsert_image(conn, {
            "file_path": str(img_file),
            "file_name": "sunset.jpg",
            "file_size": img_file.stat().st_size,
            "file_hash_sha256": src_hash,
            "phash": "dummy",
            "width": 80,
            "height": 80,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01",
            "thumbnail_path": None,
            "status": "classified",
            "primary_category_id": cat_id,
            "proposed_filename": "scenic-blue-sunset.jpg",
        })
        assert repository.count_images(conn) == 1

    plan = generate_organization_plan(str(dest_dir), db_path=temp_db)
    assert plan.total_files == 1

    # Execute with auto_remove_organized=True
    result = execute_organization_plan(plan, db_path=temp_db, auto_remove_organized=True)
    assert result.copied_count == 1
    assert result.verified_count == 1

    # 1. Source file still exists untouched
    assert img_file.exists()

    # 2. Destination file exists with verified hash
    dest_files = list(dest_dir.glob("**/*.*"))
    assert len(dest_files) == 1
    assert compute_sha256(dest_files[0]) == src_hash

    # 3. Staged image automatically removed from catalog
    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 0
        # Audit log tracks the completed copy
        cursor = conn.cursor()
        cursor.execute("SELECT status, destination_path FROM operation_logs WHERE status = 'completed'")
        row = cursor.fetchone()
        assert row is not None
        assert "scenic-blue-sunset.jpg" in row["destination_path"]
