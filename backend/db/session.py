"""
Database Session and Connection Management.

Provides connection helpers for SQLite with Write-Ahead Logging (WAL) mode,
busy timeout handling, and foreign key enforcement.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from config.settings import settings
from backend.db.schema import CURRENT_SCHEMA_VERSION, SCHEMA_SQL


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Creates and configures a SQLite connection.
    
    WAL Mode (Write-Ahead Logging):
      Allows concurrent reads while background writes occur.
    Row Factory (sqlite3.Row):
      Allows dictionary-like column access (e.g., row['file_name']).
    Busy Timeout (5000 ms):
      Prevents "database is locked" errors during rapid concurrent operations.
    """
    path = db_path or settings.database_path
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row

    # Performance and integrity pragmas
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    return conn


@contextmanager
def db_session(db_path: Optional[Path] = None):
    """
    Context manager for database transactions.
    Automatically commits on normal exit, rolls back on exception.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """
    Returns the integer schema version recorded in SQLite PRAGMA user_version.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """
    Sets the integer schema version recorded in SQLite PRAGMA user_version.
    """
    conn.execute(f"PRAGMA user_version = {int(version)};")


def migrate_db(conn: sqlite3.Connection) -> None:
    """
    Applies incremental database schema migrations up to CURRENT_SCHEMA_VERSION.
    """
    current_version = get_schema_version(conn)
    if current_version < 1:
        conn.executescript(SCHEMA_SQL)
        set_schema_version(conn, CURRENT_SCHEMA_VERSION)
        return

    if current_version < 2:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(images);")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "proposed_filename" not in existing_cols:
            conn.execute("ALTER TABLE images ADD COLUMN proposed_filename TEXT;")
        if "visual_description" not in existing_cols:
            conn.execute("ALTER TABLE images ADD COLUMN visual_description TEXT;")
        set_schema_version(conn, 2)


def init_db(db_path: Optional[Path] = None) -> None:
    """
    Initializes the database schema and seeds initial categories
    from categories.yaml if not already present.
    """
    from config.settings import Settings
    current_settings = Settings.load()

    with db_session(db_path) as conn:
        migrate_db(conn)

        # Seed and synchronize categories
        cursor = conn.cursor()
        active_codes = []
        for cat in current_settings.categories:
            active_codes.append(cat.code_name)
            cursor.execute("""
                INSERT INTO categories (code_name, display_name, description, text_prompt, is_active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(code_name) DO UPDATE SET
                    display_name=excluded.display_name,
                    description=excluded.description,
                    text_prompt=excluded.text_prompt,
                    is_active=1;
            """, (cat.code_name, cat.display_name, cat.description, cat.text_prompt))

        # Remove any legacy content categories no longer in categories.yaml
        if active_codes:
            placeholders = ",".join(["?"] * len(active_codes))
            cursor.execute(f"DELETE FROM categories WHERE code_name NOT IN ({placeholders});", active_codes)

