"""
Tests for Local AI Vision Classifier and Review Queue management.
"""

from pathlib import Path
import pytest
from PIL import Image

from backend.db.session import init_db, db_session
from backend.db import repository
from backend.core.classifier import LocalVisionClassifier


@pytest.fixture
def classifier():
    return LocalVisionClassifier()


def test_classifier_loads_taxonomy_from_settings(classifier):
    """Verifies that the classifier successfully initializes with active categories."""
    assert len(classifier.categories) >= 5
    codes = {c["code_name"] for c in classifier.categories}
    assert "animals_nature" in codes
    assert "documents_scans" in codes
    assert "screenshots_ui" in codes


def test_classify_image_returns_prediction_and_confidence(tmp_path: Path, classifier):
    """Verifies that an image produces category, subcategory, confidence, and status."""
    img_path = tmp_path / "test_photo.jpg"
    # Create bright, text-like document image (mostly white background with some lines)
    img = Image.new("RGB", (200, 200), "white")
    for x in range(20, 180, 10):
        for y in range(40, 160, 20):
            img.putpixel((x, y), (0, 0, 0))
    img.save(img_path)

    result = classifier.classify_single_image(img_path)

    assert result.category_id is not None
    assert result.category_code != ""
    assert result.category_name != ""
    assert result.subcategory != ""
    assert 0.0 <= result.confidence <= 1.0
    assert result.status in ("classified", "needs_review")


def test_classify_catalog_batch_updates_database(tmp_path: Path, temp_db: Path, classifier):
    """
    Verifies that classify_catalog processes scanned images, records predictions in
    image_classifications, updates image status, and queues ambiguous items in review_queue.
    """
    img_path = tmp_path / "sample_doc.jpg"
    Image.new("RGB", (100, 100), "white").save(img_path)

    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": str(img_path),
            "file_name": "sample_doc.jpg",
            "file_size": 1024,
            "file_hash_sha256": "hash_sample_doc",
            "phash": "dummy",
            "width": 100,
            "height": 100,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": None,
            "status": "scanned",
            "primary_category_id": None
        })

    summary = classifier.classify_catalog(db_path=temp_db)
    assert summary["total_processed"] == 1
    assert summary["classified_count"] + summary["needs_review_count"] == 1

    with db_session(temp_db) as conn:
        img = repository.get_image_by_id(conn, img_id)
        assert img["status"] in ("classified", "needs_review")
        assert img["primary_category_id"] is not None

        # Check classification record was written
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM image_classifications WHERE image_id = ?", (img_id,))
        cls_row = cursor.fetchone()
        assert cls_row is not None
        assert cls_row["confidence_score"] > 0
