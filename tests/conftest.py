"""
Pytest configuration and shared fixtures for test isolation.
"""

import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.session import init_db
from scripts.generate_test_data import generate_all_test_data


@pytest.fixture(scope="session")
def sample_images_dir(tmp_path_factory):
    """Generates a clean synthetic sample images directory in a temp location."""
    temp_dir = tmp_path_factory.mktemp("sample_images")
    generate_all_test_data(temp_dir)
    return temp_dir


@pytest.fixture
def temp_db(tmp_path):
    """Provides a fresh, isolated SQLite database initialized with the schema."""
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)
    return db_file

