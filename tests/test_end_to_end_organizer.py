"""
Full End-to-End Workflow Integration Test:
Source Selection -> Scan -> AI Classify -> Review/Override -> Dry-Run Preview -> Organize -> Verify Fidelity.
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
    3. Run local AI classification producing categories & subcategories.
    4. Review and manually override a category.
    5. Generate a dry-run folder structure preview.
    6. Execute organization copies.
    7. Verify destination folder tree, byte fidelity (SHA-256), and original preservation.
    """
    # 1. Prepare Source Directory with mixed images
    source_root = tmp_path / "My_Photos_Collection"
    source_root.mkdir()

    # Nature photo (green)
    nature_file = source_root / "forest_vacation.jpg"
    Image.new("RGB", (120, 90), "green").save(nature_file)

    # Document receipt (white text-like)
    doc_file = source_root / "grocery_receipt.png"
    doc_img = Image.new("RGB", (100, 150), "white")
    for y in range(20, 140, 15):
        for x in range(10, 90, 5):
            doc_img.putpixel((x, y), (0, 0, 0))
    doc_img.save(doc_file)

    # Unicode filename (Bangla)
    bangla_file = source_root / "সুন্দর_স্মৃতি_২০২৪.jpg"
    Image.new("RGB", (80, 80), "blue").save(bangla_file)

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

    # Step C: AI Classification
    classifier = LocalVisionClassifier()
    cls_summary = classifier.classify_catalog(db_path=temp_db)
    assert cls_summary["total_processed"] == 3

    # Step D: User Review & Category Correction
    with db_session(temp_db) as conn:
        bangla_img = next(i for i in repository.list_images(conn) if "সুন্দর" in i["file_name"])
        cats = repository.get_categories(conn)
        places_cat = next(c for c in cats if c["code_name"] == "places_travel")

        # User overrides the Bangla photo to 'Places and Travel' and approves it
        repository.override_image_category(conn, image_id=bangla_img["id"], category_id=places_cat["id"], approve=True)

        updated_bangla = repository.get_image_by_id(conn, bangla_img["id"])
        assert updated_bangla["status"] == "approved"
        assert updated_bangla["primary_category_id"] == places_cat["id"]

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

    # 2. Files exist in their categorized subfolders
    dest_files = list(valid_dest.glob("**/*.*"))
    assert len(dest_files) == 3

    # Check that Bangla file exists in Places and Travel (either directly or in subcategory)
    bangla_dest_file = next(p for p in dest_files if "সুন্দর" in p.name)
    assert "Places and Travel" in str(bangla_dest_file)
    assert bangla_dest_file.name == "সুন্দর_স্মৃতি_২০২৪.jpg"

    # 3. Source files remain completely untouched
    assert nature_file.exists()
    assert doc_file.exists()
    assert bangla_file.exists()

    # 4. Byte fidelity: SHA-256 of every destination file matches original source file
    for item in plan.items:
        dest_p = Path(item.destination_path)
        assert dest_p.exists()
        assert compute_sha256(dest_p) == compute_sha256(Path(item.source_path))

    # 5. Database audit logs
    with db_session(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM operation_logs WHERE status = 'completed'")
        assert cursor.fetchone()["count"] == 3

        # All images now marked 'organized'
        images = repository.list_images(conn)
        assert all(img["status"] == "organized" for img in images)
