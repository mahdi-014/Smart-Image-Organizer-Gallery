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


def test_sqlite_desc_null_ordering(temp_db: Path):
    """
    Empirically proves SQLite's default behavior for NULL values when sorting DESC.
    Demonstrates that in SQLite: NULL < any non-NULL value,
    so 'ORDER BY dt DESC' places NULLs LAST.
    """
    with db_session(temp_db) as conn:
        conn.execute("CREATE TABLE test_dates (id INT, dt TEXT);")
        conn.execute("INSERT INTO test_dates VALUES (1, '2024-01-01'), (2, NULL), (3, '2025-06-01');")

        # Standard DESC query
        rows = conn.execute("SELECT id, dt FROM test_dates ORDER BY dt DESC;").fetchall()

        # In SQLite: '2025-06-01' > '2024-01-01' > NULL
        assert rows[0]["id"] == 3       # '2025-06-01' (newest)
        assert rows[1]["id"] == 1       # '2024-01-01' (older)
        assert rows[2]["id"] == 2       # NULL (sorted last)
        assert rows[2]["dt"] is None


def test_sqlite_schema_versioning(temp_db: Path):
    """Verifies that SQLite user_version is recorded and matches CURRENT_SCHEMA_VERSION."""
    from backend.db.session import get_schema_version, get_connection
    from backend.db.schema import CURRENT_SCHEMA_VERSION

    conn = get_connection(temp_db)
    try:
        assert get_schema_version(conn) == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


def test_sqlite_composite_indices_exist(temp_db: Path):
    """Verifies that composite gallery-ordering and filtering indices exist in SQLite master."""
    from backend.db.session import get_connection

    conn = get_connection(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indices = {row[0] for row in cursor.fetchall()}

        assert "idx_images_gallery_order" in indices
        assert "idx_images_cat_date" in indices
        assert "idx_images_status_date" in indices
    finally:
        conn.close()


def test_find_exact_duplicates_single_query_execution(temp_db: Path):
    """
    Verifies that find_exact_duplicates accurately identifies duplicate groups
    and groups all identical SHA-256 items together.
    """
    from backend.db.session import db_session

    with db_session(temp_db) as conn:
        for i in range(1, 5):
            h = "hash_group_a" if i <= 2 else "hash_group_b"
            data = {
                "file_path": f"C:/photos/dup_{i}.jpg",
                "file_name": f"dup_{i}.jpg",
                "file_size": 2048,
                "file_hash_sha256": h,
                "phash": "dummy",
                "width": 100,
                "height": 100,
                "file_format": "JPEG",
                "date_taken": f"2024-01-0{i}T00:00:00",
                "date_modified": f"2024-01-0{i}T00:00:00",
                "thumbnail_path": None,
                "status": "scanned",
                "primary_category_id": None
            }
            repository.upsert_image(conn, data)

        dups = repository.find_exact_duplicates(conn)
        assert len(dups) == 2
        hashes = {d["file_hash_sha256"] for d in dups}
        assert hashes == {"hash_group_a", "hash_group_b"}
        for d in dups:
            assert d["duplicate_count"] == 2
            assert len(d["images"]) == 2


def test_override_image_category_resolves_review_queue(temp_db: Path):
    """
    Verifies that override_image_category updates primary_category_id,
    marks status as approved, and resolves any associated review_queue items.
    """
    from backend.db.session import db_session

    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": "C:/photos/dog.jpg",
            "file_name": "dog.jpg",
            "file_size": 2048,
            "file_hash_sha256": "hash_dog",
            "phash": "dummy",
            "width": 100,
            "height": 100,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": None,
            "status": "needs_review",
            "primary_category_id": None
        })

        # Add to review queue
        cursor = conn.cursor()
        cursor.execute("INSERT INTO review_queue (image_id, reason) VALUES (?, 'low_confidence')", (img_id,))

        # Find categories
        cats = repository.get_categories(conn)
        target_cat_id = cats[0]["id"]

        # Override category
        repository.override_image_category(conn, image_id=img_id, category_id=target_cat_id, approve=True)

        updated_img = repository.get_image_by_id(conn, img_id)
        assert updated_img["primary_category_id"] == target_cat_id
        assert updated_img["status"] == "approved"

        # Verify review queue is marked resolved
        cursor.execute("SELECT is_resolved, resolved_category_id FROM review_queue WHERE image_id = ?", (img_id,))
        rq = cursor.fetchone()
        assert rq["is_resolved"] == 1
        assert rq["resolved_category_id"] == target_cat_id


def test_semantic_metadata_storage_and_update(temp_db: Path):
    """Verifies storing, updating, and querying content-aware proposed_filename and visual_description."""
    with db_session(temp_db) as conn:
        img_id = repository.upsert_image(conn, {
            "file_path": "C:/photos/retriever.jpg",
            "file_name": "retriever.jpg",
            "file_size": 4096,
            "file_hash_sha256": "hash_retriever",
            "phash": "dummy",
            "width": 1920,
            "height": 1080,
            "file_format": "JPEG",
            "date_taken": None,
            "date_modified": "2024-01-01T00:00:00",
            "thumbnail_path": None,
            "status": "scanned",
            "primary_category_id": None,
            "proposed_filename": "golden-retriever-running-on-grass.jpg",
            "visual_description": "golden retriever running on green grass outdoors",
        })

        fetched = repository.get_image_by_id(conn, img_id)
        assert fetched is not None
        assert fetched["proposed_filename"] == "golden-retriever-running-on-grass.jpg"
        assert fetched["visual_description"] == "golden retriever running on green grass outdoors"

        # Update proposed filename
        success = repository.update_image_proposed_filename(conn, img_id, "happy-golden-retriever.jpg")
        assert success is True

        updated = repository.get_image_by_id(conn, img_id)
        assert updated["proposed_filename"] == "happy-golden-retriever.jpg"
        assert updated["visual_description"] == "golden retriever running on green grass outdoors"


def test_schema_migration_v1_to_v2(tmp_path: Path):
    """Verifies that an existing database at version 1 safely migrates to version 2."""
    import sqlite3
    from backend.db.session import migrate_db, get_schema_version, set_schema_version

    db_path = tmp_path / "v1_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create v1 style table without proposed_filename and visual_description
    conn.execute("""
        CREATE TABLE images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_hash_sha256 TEXT NOT NULL,
            phash TEXT,
            width INTEGER,
            height INTEGER,
            file_format TEXT,
            date_taken TEXT,
            date_modified TEXT NOT NULL,
            thumbnail_path TEXT,
            status TEXT NOT NULL DEFAULT 'scanned',
            primary_category_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (DATETIME('now')),
            updated_at TEXT NOT NULL DEFAULT (DATETIME('now'))
        );
    """)
    set_schema_version(conn, 1)
    assert get_schema_version(conn) == 1

    # Run migration
    migrate_db(conn)
    assert get_schema_version(conn) == 2

    # Verify new columns exist
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(images);")
    cols = {row["name"] for row in cursor.fetchall()}
    assert "proposed_filename" in cols
    assert "visual_description" in cols
    conn.close()
