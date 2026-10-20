"""
Database Schema Definitions for SQLite.

Contains DDL statements for creating the tables, indices, and views
required by the Smart Image Organizer & Gallery application.
"""

SCHEMA_SQL = """
-- 1. Categories Table (Configurable Taxonomy)
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    text_prompt TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- 2. Core Images Table (Read-Only Source Metadata Catalog)
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,          -- Absolute source path on disk
    file_name TEXT NOT NULL,                 -- e.g., 'photo_001.jpg'
    file_size INTEGER NOT NULL,              -- Size in bytes
    file_hash_sha256 TEXT NOT NULL,          -- Exact duplicate matching
    phash TEXT,                              -- Perceptual difference hash (64-bit hex)
    width INTEGER,                           -- Pixel width
    height INTEGER,                          -- Pixel height
    file_format TEXT,                        -- 'JPEG', 'PNG', 'WEBP', etc.
    date_taken TEXT,                         -- From EXIF DateTimeOriginal (ISO-8601 string)
    date_modified TEXT NOT NULL,             -- Filesystem modification timestamp
    thumbnail_path TEXT,                     -- Path to pre-rendered small WebP thumbnail
    status TEXT NOT NULL DEFAULT 'scanned',  -- 'scanned', 'classified', 'needs_review', 'approved', 'organized'
    primary_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (DATETIME('now')),
    updated_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

-- Indices for rapid queries over 10,000+ items
CREATE INDEX IF NOT EXISTS idx_images_hash ON images(file_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE INDEX IF NOT EXISTS idx_images_category ON images(primary_category_id);
CREATE INDEX IF NOT EXISTS idx_images_date_taken ON images(date_taken);

-- 3. AI Classification History (Local & Cloud)
CREATE TABLE IF NOT EXISTS image_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,                  -- 'local_clip', 'local_siglip', 'gemini'
    model_name TEXT NOT NULL,                -- e.g. 'ViT-B-32', 'gemini-2.5-flash'
    predicted_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    confidence_score REAL NOT NULL,          -- Range 0.0 to 1.0
    margin_score REAL,                       -- Score gap between top-1 and top-2
    raw_scores_json TEXT,                    -- Full probability distribution as JSON
    suggested_tags_json TEXT,                -- Array of tags as JSON
    created_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

CREATE INDEX IF NOT EXISTS idx_classifications_image ON image_classifications(image_id);

-- 4. Tags Dictionary
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- 5. Image-Tag Many-to-Many Association
CREATE TABLE IF NOT EXISTS image_tags (
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'local_ai', -- 'local_ai', 'gemini', 'manual'
    confidence REAL DEFAULT 1.0,
    PRIMARY KEY (image_id, tag_id)
);

-- 6. Needs Review Queue
CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,                    -- 'low_confidence', 'ambiguous_margin', 'duplicate_conflict', 'manual_flag'
    is_resolved INTEGER NOT NULL DEFAULT 0,
    resolved_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (DATETIME('now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_unresolved ON review_queue(is_resolved);

-- 7. Audit, Dry-Run and Execution Operation Logs
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,                  -- UUID grouping a single organization execution
    operation_type TEXT NOT NULL,            -- 'scan', 'classify', 'dry_run', 'copy_rename', 'rollback'
    image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
    source_path TEXT NOT NULL,
    proposed_path TEXT,
    destination_path TEXT,
    status TEXT NOT NULL,                    -- 'proposed', 'in_progress', 'completed', 'failed', 'rolled_back'
    error_message TEXT,
    executed_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

CREATE INDEX IF NOT EXISTS idx_logs_batch ON operation_logs(batch_id);
"""

