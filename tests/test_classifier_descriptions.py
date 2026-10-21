"""
Tests for Visual Content Analysis, Description Generation, and Proposed Filenames.
"""

from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from backend.core.classifier import LocalVisionClassifier
from backend.db.session import init_db, db_session
from backend.db import repository


@pytest.fixture
def classifier():
    return LocalVisionClassifier(high_confidence_threshold=0.55, min_margin=0.10)


def create_synthetic_document_image(path: Path):
    """Creates a white document-like image with black horizontal text lines."""
    img = Image.new("RGB", (600, 800), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    # Draw dark text-like strokes
    for y in range(80, 700, 30):
        draw.line([(50, y), (550, y)], fill=(30, 30, 30), width=4)
        draw.line([(60, y + 8), (400, y + 8)], fill=(60, 60, 60), width=2)
    img.save(path)


def create_synthetic_nature_image(path: Path):
    """Creates a landscape image with blue sky and green grass."""
    img = Image.new("RGB", (800, 600), color=(70, 160, 240))  # Sky blue
    draw = ImageDraw.Draw(img)
    # Green ground
    draw.rectangle([0, 350, 800, 600], fill=(45, 140, 45))
    # Sun / warm horizon
    draw.ellipse([600, 150, 700, 250], fill=(255, 215, 60))
    img.save(path)


def create_synthetic_terminal_screenshot(path: Path):
    """Creates a dark terminal / code screenshot with code-like lines."""
    img = Image.new("RGB", (900, 500), color=(25, 28, 35))  # Dark console
    draw = ImageDraw.Draw(img)
    # Window header bar
    draw.rectangle([0, 0, 900, 35], fill=(45, 48, 55))
    # Colorful code lines
    colors = [(220, 80, 80), (80, 200, 120), (100, 160, 250), (230, 200, 80)]
    for idx, y in enumerate(range(60, 440, 25)):
        c = colors[idx % len(colors)]
        draw.line([(40, y), (350 + (idx * 20 % 300), y)], fill=c, width=3)
    img.save(path)


def create_synthetic_warm_food_image(path: Path):
    """Creates a warm food / dessert dish image."""
    img = Image.new("RGB", (600, 600), color=(245, 235, 220))  # Table
    draw = ImageDraw.Draw(img)
    # Plate
    draw.ellipse([100, 100, 500, 500], fill=(255, 255, 255), outline=(200, 200, 200), width=3)
    # Warm rich cake / pastry
    draw.ellipse([160, 160, 440, 440], fill=(120, 50, 25))
    # Strawberry red accents
    draw.ellipse([260, 260, 340, 340], fill=(220, 30, 40))
    img.save(path)


def test_classify_document_detects_visual_content(classifier, tmp_path: Path):
    """Verifies that high-brightness text-dense images are recognized as documents."""
    doc_path = tmp_path / "DSC_0042.PNG"
    create_synthetic_document_image(doc_path)

    res = classifier.classify_single_image(doc_path)
    assert res.category_code == "documents_scans"
    assert res.subcategory in ("Scanned_Documents", "Receipts_Invoices", "Forms_Letters")
    assert "document" in res.visual_description.lower() or "receipt" in res.visual_description.lower()
    assert res.proposed_filename.endswith(".png")
    assert ("document" in res.proposed_filename or "receipt" in res.proposed_filename)


def test_classify_nature_detects_landscape(classifier, tmp_path: Path):
    """Verifies that sky + grass palettes are recognized as nature landscapes."""
    nature_path = tmp_path / "IMG_9941.JPG"
    create_synthetic_nature_image(nature_path)

    res = classifier.classify_single_image(nature_path)
    assert res.category_code == "animals_nature"
    assert res.subcategory in ("Landscapes", "Wildlife_Pets", "Plants_Flowers")
    assert "landscape" in res.visual_description.lower() or "nature" in res.visual_description.lower()
    assert res.proposed_filename.endswith(".jpg")
    assert not res.proposed_filename.startswith("IMG_9941")


def test_classify_terminal_screenshot(classifier, tmp_path: Path):
    """Verifies that dark console window layouts are recognized as UI screenshots."""
    screen_path = tmp_path / "ScreenShot_2026.png"
    create_synthetic_terminal_screenshot(screen_path)

    res = classifier.classify_single_image(screen_path)
    assert res.category_code == "screenshots_ui"
    assert "screenshot" in res.visual_description.lower() or "ui" in res.visual_description.lower() or "terminal" in res.visual_description.lower()
    assert res.proposed_filename.endswith(".png")


def test_classify_warm_food_image(classifier, tmp_path: Path):
    """Verifies that warm-toned plate compositions are recognized as food/meals."""
    food_path = tmp_path / "P1010345.jpg"
    create_synthetic_warm_food_image(food_path)

    res = classifier.classify_single_image(food_path)
    assert res.category_code == "food_cooking"
    assert "food" in res.visual_description.lower() or "meal" in res.visual_description.lower() or "dessert" in res.visual_description.lower()
    assert res.proposed_filename.endswith(".jpg")


def test_classify_catalog_populates_semantic_fields_in_db(classifier, tmp_path: Path, temp_db: Path):
    """Verifies classify_catalog writes proposed_filename and visual_description into SQLite."""
    img_path = tmp_path / "DSC_sample.png"
    create_synthetic_document_image(img_path)

    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": str(img_path),
            "file_name": img_path.name,
            "file_size": 2048,
            "file_hash_sha256": "fake_sha_sample",
            "phash": "dummy",
            "width": 600,
            "height": 800,
            "file_format": "PNG",
            "date_taken": None,
            "date_modified": "2026-03-01T12:00:00",
            "thumbnail_path": None,
            "status": "scanned",
            "primary_category_id": None,
        })

    summary = classifier.classify_catalog(db_path=temp_db)
    assert summary["total_processed"] >= 1

    with db_session(temp_db) as conn:
        record = repository.get_image_by_id(conn, img_id)
        assert record is not None
        assert record["status"] in ("classified", "needs_review")
        assert record["proposed_filename"] is not None
        assert len(record["proposed_filename"]) > 5
        assert record["proposed_filename"].endswith(".png")
        assert record["visual_description"] is not None
        assert len(record["visual_description"]) > 5
