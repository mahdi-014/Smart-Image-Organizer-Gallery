"""
End-to-End System Integration Test for Local File Organizer & Explorer Workflow.

Validates the full user journey:
Select Folder -> Scan -> AI Visual Content Recognition -> Descriptive Renaming ->
Review & Override -> Dry-Run Preview -> Execute Copy (shutil.copy2) -> SHA-256 Verification.
"""

from pathlib import Path
import pytest
from PIL import Image

from backend.db.session import init_db, db_session
from backend.db import repository
from backend.core.hasher import compute_sha256
from backend.core.scanner import scan_directory
from backend.core.classifier import LocalVisionClassifier
from backend.core.organizer import generate_organization_plan, execute_organization_plan
from backend.core.folder_service import validate_local_folder, check_folder_overlap


def test_full_organizer_product_workflow(tmp_path: Path, temp_db: Path):
    """
    Demonstrates the complete end-to-end product workflow requested by the user:
    1. Select source and destination folders.
    2. Scan real local image files (including Unicode filenames).
    3. Run local AI visual recognition producing categories, subcategories, and descriptive slugs.
    4. Review and manually override a category and proposed filename.
    5. Generate a dry-run folder structure preview.
    6. Execute organization copies.
    7. Verify destination folder tree, byte fidelity (SHA-256), and original preservation.
    """
    # 1. Prepare Source Directory with mixed images
    source_root = tmp_path / "My_Photos_Collection"
    source_root.mkdir()

    # Nature photo (green + blue)
    nature_file = source_root / "IMG_8271.jpg"
    nature_img = Image.new("RGB", (120, 90), (70, 160, 240))
    for y in range(45, 90):
        for x in range(120):
            nature_img.putpixel((x, y), (45, 140, 45))
    nature_img.save(nature_file)

    # Document receipt (white text-like)
    doc_file = source_root / "DSC_0042.png"
    doc_img = Image.new("RGB", (100, 150), "white")
    for y in range(20, 140, 15):
        for x in range(10, 90, 5):
            doc_img.putpixel((x, y), (0, 0, 0))
    doc_img.save(doc_file)

    # Unicode filename (Bangla)
    bangla_file = source_root / "সুন্দর_স্মৃতি_২০২৪.jpg"
    Image.new("RGB", (80, 80), (120, 50, 25)).save(bangla_file)

    dest_root = tmp_path / "Organized_Library"

    # Step A: Validate Folders & Safety
    valid_src = validate_local_folder(str(source_root), must_exist=True)
    valid_dest = validate_local_folder(str(dest_root), must_exist=False)
    assert check_folder_overlap(valid_src, valid_dest) is False

    # Step B: Scan Images
    scan_prog = scan_directory(str(valid_src), db_path=temp_db, exclude_dirs=[str(valid_dest)])
    assert scan_prog.is_complete is True
    assert scan_prog.total_found == 3
    assert scan_prog.processed_count == 3
    assert scan_prog.error_count == 0

    with db_session(temp_db) as conn:
        assert repository.count_images(conn) == 3

    # Step C: AI Classification & Descriptive Renaming
    classifier = LocalVisionClassifier()
    cls_summary = classifier.classify_catalog(db_path=temp_db)
    assert cls_summary["total_processed"] == 3

    # Step D: User Review & Manual Override
    with db_session(temp_db) as conn:
        # Check that nature image was given a semantic proposed filename
        nature_record = next(i for i in repository.list_images(conn) if i["file_name"] == "IMG_8271.jpg")
        assert nature_record["proposed_filename"] is not None
        assert "IMG_8271" not in nature_record["proposed_filename"]
        assert "landscape" in nature_record["proposed_filename"] or "nature" in nature_record["proposed_filename"]

        # User overrides the Bangla photo to 'Places and Travel' and custom filename
        bangla_img = next(i for i in repository.list_images(conn) if "সুন্দর" in i["file_name"])
        cats = repository.get_categories(conn)
        places_cat = next(c for c in cats if c["code_name"] == "places_travel")

        repository.override_image_category(conn, image_id=bangla_img["id"], category_id=places_cat["id"], approve=True)
        repository.update_image_proposed_filename(conn, image_id=bangla_img["id"], proposed_filename="scenic-holiday-memories.jpg")

        updated_bangla = repository.get_image_by_id(conn, bangla_img["id"])
        assert updated_bangla["status"] == "approved"
        assert updated_bangla["primary_category_id"] == places_cat["id"]
        assert updated_bangla["proposed_filename"] == "scenic-holiday-memories.jpg"

    # Step E: Dry-Run Preview
    plan = generate_organization_plan(
        destination_dir=str(valid_dest),
        db_path=temp_db,
        include_needs_review=True,
    )
    assert plan.total_files == 3
    # Verify dry-run did not touch disk
    assert not valid_dest.exists()

    # Step F: Approve & Execute Organization
    result = execute_organization_plan(plan, db_path=temp_db)
    assert result.total_files == 3
    assert result.copied_count == 3
    assert result.verified_count == 3
    assert result.failed_count == 0

    # Step G: Rigorous Verification of Results
    # 1. Destination directories exist
    assert valid_dest.exists()

    # 2. Files exist in their categorized subfolders with new semantic filenames
    dest_files = list(valid_dest.glob("**/*.*"))
    assert len(dest_files) == 3

    # Check overridden Bangla photo
    bangla_dest_file = next(p for p in dest_files if "scenic-holiday-memories" in p.name)
    assert "Places and Travel" in str(bangla_dest_file)
    assert bangla_dest_file.name == "scenic-holiday-memories.jpg"

    # Check document was renamed semantically
    doc_dest_file = next(p for p in dest_files if p.suffix.lower() == ".png")
    assert "Documents and Scans" in str(doc_dest_file)
    assert "document" in doc_dest_file.name or "receipt" in doc_dest_file.name

    # 3. Source files remain completely untouched with original names
    assert nature_file.exists()
    assert nature_file.name == "IMG_8271.jpg"
    assert doc_file.exists()
    assert doc_file.name == "DSC_0042.png"
    assert bangla_file.exists()
    assert bangla_file.name == "সুন্দর_স্মৃতি_২০২৪.jpg"

    # 4. Byte fidelity: SHA-256 of every destination file matches original source file
    for item in plan.items:
        dest_p = Path(item.destination_path)
        assert dest_p.exists()
        assert compute_sha256(dest_p) == compute_sha256(Path(item.source_path))

    # 5. Database audit logs track original and destination paths
    with db_session(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM operation_logs WHERE status = 'completed'")
        assert cursor.fetchone()["count"] == 3

        # All images now marked 'organized'
        images = repository.list_images(conn)
        assert all(img["status"] == "organized" for img in images)
