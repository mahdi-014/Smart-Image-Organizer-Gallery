"""
Unit tests for SQLite database schema, WAL mode, and repository operations.
"""

from pathlib import Path
from backend.db.session import db_session
from backend.db import repository


def test_schema_and_categories_seeding(temp_db: Path):
    """Verifies that tables are created and categories seeded from categories.yaml."""
    with db_session(temp_db) as conn:
        # Check WAL mode
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode.lower() == "wal"

        # Check seeded categories
        cats = repository.get_categories(conn)
        assert len(cats) == 13
        code_names = [c["code_name"] for c in cats]
        assert "products_ecommerce" in code_names
        assert "screenshots_ui" in code_names
        assert "other" in code_names
        # 'needs_review' must NOT be a content category
        assert "needs_review" not in code_names


def test_upsert_and_retrieve_image(temp_db: Path):
    """Verifies inserting and querying an image record."""
    with db_session(temp_db) as conn:
        dummy_data = {
            "file_path": "C:/fake/path/test.jpg",
            "file_name": "test.jpg",
            "file_size": 1024,
            "file_hash_sha256": "fake_hash_12345",
            "phash": "0123456789abcdef",
            "width": 800,
            "height": 600,
            "file_format": "JPEG",
            "date_taken": "2024-01-01T00:00:00",
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": "data/thumbnails/test.webp",
            "status": "scanned",
            "primary_category_id": None
        }

        image_id = repository.upsert_image(conn, dummy_data)
        assert image_id > 0

        fetched = repository.get_image_by_id(conn, image_id)
        assert fetched is not None
        assert fetched["file_name"] == "test.jpg"
        assert fetched["file_size"] == 1024
        assert fetched["file_hash_sha256"] == "fake_hash_12345"

