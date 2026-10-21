"""
Tests for Safe File Organizer Engine: Dry-run planning, collision resolution,
shutil.copy2 execution, SHA-256 copy verification, and operation logging.
"""

from pathlib import Path
import pytest
from PIL import Image

from backend.db.session import init_db, db_session
from backend.db import repository
from backend.core.hasher import compute_sha256
from backend.core.organizer import (
    generate_organization_plan,
    execute_organization_plan,
)


@pytest.fixture
def setup_images(tmp_path: Path, temp_db: Path):
    """Sets up synthetic catalog with 2 classified images."""
    src_dir = tmp_path / "source_photos"
    src_dir.mkdir()

    img1_path = src_dir / "mountain.jpg"
    Image.new("RGB", (100, 100), "green").save(img1_path)
    hash1 = compute_sha256(img1_path)

    img2_path = src_dir / "invoice.png"
    Image.new("RGB", (100, 100), "white").save(img2_path)
    hash2 = compute_sha256(img2_path)

    with db_session(temp_db) as conn:
        cats = repository.get_categories(conn)
        cat_nature = next(c for c in cats if c["code_name"] == "animals_nature")
        cat_docs = next(c for c in cats if c["code_name"] == "documents_scans")

        id1 = repository.upsert_image(conn, {
            "file_path": str(img1_path),
            "file_name": "mountain.jpg",
            "file_size": img1_path.stat().st_size,
            "file_hash_sha256": hash1,
            "phash": "phash1",
            "width": 100,
            "height": 100,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": None,
            "status": "classified",
            "primary_category_id": cat_nature["id"]
        })

        id2 = repository.upsert_image(conn, {
            "file_path": str(img2_path),
            "file_name": "invoice.png",
            "file_size": img2_path.stat().st_size,
            "file_hash_sha256": hash2,
            "phash": "phash2",
            "width": 100,
            "height": 100,
            "file_format": "PNG",
            "date_taken": None,
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": None,
            "status": "approved",
            "primary_category_id": cat_docs["id"]
        })

    return {
        "src_dir": src_dir,
        "img1": img1_path,
        "img2": img2_path,
        "id1": id1,
        "id2": id2,
        "hash1": hash1,
        "hash2": hash2,
    }


def test_generate_dry_run_plan_does_not_touch_disk(tmp_path: Path, temp_db: Path, setup_images):
    """Verifies dry-run plan generates expected destination tree without creating files."""
    dest_dir = tmp_path / "Organized_Destination"
    # Destination does not exist yet
    assert not dest_dir.exists()

    plan = generate_organization_plan(
        destination_dir=str(dest_dir),
        db_path=temp_db,
    )

    assert plan.total_files == 2
    assert len(plan.items) == 2
    # Ensure dry run did NOT create any folders or files
    assert not dest_dir.exists()

    # Verify proposed paths
    dest_paths = [Path(item.destination_path) for item in plan.items]
    assert any("Animals and Nature" in str(p) for p in dest_paths)
    assert any("Documents and Scans" in str(p) for p in dest_paths)


def test_collision_resolution_in_plan(tmp_path: Path, temp_db: Path):
    """Verifies that duplicate file names in different source folders get unique target names."""
    src_dir1 = tmp_path / "folder_a"
    src_dir2 = tmp_path / "folder_b"
    src_dir1.mkdir()
    src_dir2.mkdir()

    img1 = src_dir1 / "vacation.jpg"
    img2 = src_dir2 / "vacation.jpg"
    Image.new("RGB", (50, 50), "red").save(img1)
    Image.new("RGB", (50, 50), "blue").save(img2)

    with db_session(temp_db) as conn:
        cats = repository.get_categories(conn)
        cat_id = cats[0]["id"]
        defaults = {
            "phash": "p1", "width": 50, "height": 50, "file_format": "JPEG",
            "date_taken": None, "thumbnail_path": None, "status": "approved",
            "primary_category_id": cat_id, "date_modified": "2024-01-01"
        }
        repository.upsert_image(conn, {
            "file_path": str(img1), "file_name": "vacation.jpg", "file_size": 100,
            "file_hash_sha256": "h1", **defaults
        })
        repository.upsert_image(conn, {
            "file_path": str(img2), "file_name": "vacation.jpg", "file_size": 200,
            "file_hash_sha256": "h2", **defaults
        })

    dest_dir = tmp_path / "Organized_Test"
    plan = generate_organization_plan(str(dest_dir), db_path=temp_db)

    assert plan.total_files == 2
    names = [Path(item.destination_path).name for item in plan.items]
    assert "vacation.jpg" in names
    assert "vacation (2).jpg" in names


def test_execute_organization_plan_copies_and_verifies_sha256(tmp_path: Path, temp_db: Path, setup_images):
    """
    Verifies that execute_organization_plan:
    1. Copies original files byte-for-byte with shutil.copy2
    2. Leaves original source files untouched
    3. Verifies SHA-256 checksums of destination copies
    4. Logs completed entries in operation_logs
    5. Updates image status in catalog to 'organized'
    """
    dest_dir = tmp_path / "Organized_Destination"
    plan = generate_organization_plan(str(dest_dir), db_path=temp_db)

    result = execute_organization_plan(plan, db_path=temp_db)

    assert result.total_files == 2
    assert result.copied_count == 2
    assert result.verified_count == 2
    assert result.failed_count == 0

    # 1. Verify original source files still exist untouched
    assert setup_images["img1"].exists()
    assert setup_images["img2"].exists()

    # 2. Verify destination files exist and match SHA-256
    for item in plan.items:
        dest_p = Path(item.destination_path)
        assert dest_p.exists()
        assert compute_sha256(dest_p) == item.source_hash

    # 3. Verify operation_logs and image status in database
    with db_session(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM operation_logs WHERE status = 'completed'")
        assert cursor.fetchone()["count"] == 2

        img1 = repository.get_image_by_id(conn, setup_images["id1"])
        assert img1["status"] == "organized"
