"""
Application Settings & Configuration Module.

Loads configuration from environment variables (.env) and yaml taxonomy.
Provides path constants, image extension filters, and runtime defaults.
"""

from pathlib import Path
from typing import List, Dict, Any, Set
import os
import yaml
from pydantic import BaseModel, Field

# Base Directories
# PROJECT_ROOT resolves to d:\Smart Image Organizer & Gallery
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
DATABASE_PATH = DATA_DIR / "gallery.db"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

# Image Scanning Filters (case-insensitive)
# Supports standard web formats and legacy/uncompressed formats
SUPPORTED_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".gif", ".tif", ".tiff"
}

# Thumbnail Configuration
THUMBNAIL_MAX_SIZE = (300, 300)
THUMBNAIL_FORMAT = "WEBP"
THUMBNAIL_QUALITY = 85

# Hashing Chunk Size: 64 KB (65536 bytes)
# Reads files incrementally to avoid consuming large amounts of RAM.
HASH_CHUNK_SIZE = 65536


class CategoryDefinition(BaseModel):
    """Schema for a single category defined in categories.yaml."""
    code_name: str
    display_name: str
    description: str
    text_prompt: str


class Settings(BaseModel):
    """Global runtime settings."""
    app_name: str = "Smart Image Organizer & Gallery"
    app_env: str = Field(default="development")
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True

    # Storage Paths
    project_root: Path = PROJECT_ROOT
    data_dir: Path = DATA_DIR
    thumbnails_dir: Path = THUMBNAILS_DIR
    database_path: Path = DATABASE_PATH

    # Cloud AI
    enable_gemini_api: bool = False
    gemini_api_key: str = ""

    # Categories
    categories: List[CategoryDefinition] = []

    @classmethod
    def load(cls) -> "Settings":
        """Factory method to load settings from environment and categories.yaml."""
        # Load environment variables from .env if present
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)

        enable_gemini = os.getenv("ENABLE_GEMINI_API", "False").lower() in ("true", "1", "yes")
        gemini_key = os.getenv("GEMINI_API_KEY", "")

        # Load categories.yaml
        yaml_path = CONFIG_DIR / "categories.yaml"
        categories_list: List[CategoryDefinition] = []
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                raw_cats = content.get("categories", [])
                categories_list = [CategoryDefinition(**c) for c in raw_cats]

        return cls(
            enable_gemini_api=enable_gemini,
            gemini_api_key=gemini_key,
            categories=categories_list,
        )


# Singleton instance for easy import across modules
settings = Settings.load()

