"""
Application Settings & Configuration Module.

Loads configuration from environment variables (.env) and yaml taxonomy.
Provides path constants, image extension filters, and runtime defaults.
"""

from pathlib import Path
from typing import List, Dict, Any, Set, Optional, Union
import os
import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

# Base Directories
# PROJECT_ROOT resolves to d:\Smart Image Organizer & Gallery
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = (PROJECT_ROOT / "data").resolve()
THUMBNAILS_DIR = (DATA_DIR / "thumbnails").resolve()
DATABASE_PATH = (DATA_DIR / "gallery.db").resolve()

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

# Maximum allowed image pixels (~89.48 Megapixels).
# Explicit application safety ceiling protecting against decompression bomb attacks.
DEFAULT_MAX_IMAGE_PIXELS = 89_478_485

TRUE_BOOLEAN_STRINGS: Set[str] = {"true", "1", "yes", "t"}
FALSE_BOOLEAN_STRINGS: Set[str] = {"false", "0", "no", "f"}


def resolve_config_path(raw: Optional[str], default: Path, base_dir: Path = PROJECT_ROOT) -> Path:
    """
    Resolves an environment path setting:
    - If None, empty, or whitespace-only, returns default.
    - If absolute, returns Path(raw).resolve().
    - If relative, resolves against base_dir.
    """
    if raw is None or not raw.strip():
        return default
    p = Path(raw.strip())
    if p.is_absolute():
        return p.resolve()
    return (base_dir / p).resolve()


def parse_bool(key: str, raw: Optional[str], default: bool) -> bool:
    """
    Parses boolean string explicitly or returns default.
    Raises ValueError on unsupported values.
    """
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned in TRUE_BOOLEAN_STRINGS:
        return True
    if cleaned in FALSE_BOOLEAN_STRINGS:
        return False
    supported = sorted(TRUE_BOOLEAN_STRINGS | FALSE_BOOLEAN_STRINGS)
    raise ValueError(
        f"Invalid boolean value for {key}: '{raw}'. "
        f"Supported values: {', '.join(supported)}."
    )


def parse_port(raw: Optional[str], default: int = 8000) -> int:
    """
    Parses PORT integer between 1 and 65535 or returns default.
    """
    if raw is None:
        return default
    cleaned = raw.strip()
    try:
        val = int(cleaned)
    except ValueError:
        raise ValueError(f"Invalid PORT '{raw}': must be an integer.")
    if not (1 <= val <= 65535):
        raise ValueError(f"Invalid PORT '{raw}': must be between 1 and 65535.")
    return val


def parse_positive_int(key: str, raw: Optional[str], default: int) -> int:
    """
    Parses positive integer or returns default.
    """
    if raw is None:
        return default
    cleaned = raw.strip()
    try:
        val = int(cleaned)
    except ValueError:
        raise ValueError(f"Invalid {key} '{raw}': must be an integer.")
    if val <= 0:
        raise ValueError(f"Invalid {key} '{raw}': must be a positive integer.")
    return val


def get_env_value(
    key: str,
    dotenv_dict: Dict[str, Optional[str]],
    default: Optional[str] = None
) -> Optional[str]:
    """
    Retrieves configuration value with precedence:
    1. os.environ (if set and non-whitespace)
    2. dotenv_dict (if set and non-whitespace)
    3. default
    Missing, empty, or whitespace-only values are treated as unset.
    """
    val = os.environ.get(key)
    if val is not None and val.strip():
        return val.strip()

    val = dotenv_dict.get(key)
    if val is not None and val.strip():
        return val.strip()

    return default


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
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS

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

    def ensure_directories(self) -> None:
        """
        Explicitly creates runtime storage directories (data_dir and thumbnails_dir).
        Must be invoked intentionally by runtime runners, never during module import.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, env_file: Optional[Union[str, Path]] = None) -> "Settings":
        """
        Factory method to load settings with precedence:
        Process environment variables > .env file > application defaults.
        """
        env_path = Path(env_file) if env_file is not None else (PROJECT_ROOT / ".env")
        dotenv_dict: Dict[str, Optional[str]] = {}
        if env_path.is_file():
            dotenv_dict = {
                k: v for k, v in dotenv_values(env_path).items()
                if v is not None
            }

        # 1. Directory & Storage Configuration
        raw_data_dir = get_env_value("DATA_DIR", dotenv_dict)
        data_dir = resolve_config_path(raw_data_dir, default=DATA_DIR, base_dir=PROJECT_ROOT)

        raw_thumbs = get_env_value("THUMBNAILS_DIR", dotenv_dict)
        thumbnails_dir = resolve_config_path(
            raw_thumbs,
            default=(data_dir / "thumbnails").resolve(),
            base_dir=PROJECT_ROOT
        )

        raw_db = get_env_value("DATABASE_PATH", dotenv_dict)
        database_path = resolve_config_path(
            raw_db,
            default=(data_dir / "gallery.db").resolve(),
            base_dir=PROJECT_ROOT
        )

        # 2. Application Runtime Settings
        raw_app_env = get_env_value("APP_ENV", dotenv_dict, default="development")
        raw_host = get_env_value("HOST", dotenv_dict, default="127.0.0.1")
        raw_port = get_env_value("PORT", dotenv_dict)
        port = parse_port(raw_port, default=8000)

        raw_debug = get_env_value("DEBUG", dotenv_dict)
        debug = parse_bool("DEBUG", raw_debug, default=True)

        raw_pixels = get_env_value("MAX_IMAGE_PIXELS", dotenv_dict)
        max_image_pixels = parse_positive_int(
            "MAX_IMAGE_PIXELS",
            raw_pixels,
            default=DEFAULT_MAX_IMAGE_PIXELS
        )

        # 3. Cloud AI Settings
        raw_enable_gemini = get_env_value("ENABLE_GEMINI_API", dotenv_dict)
        enable_gemini = parse_bool("ENABLE_GEMINI_API", raw_enable_gemini, default=False)
        gemini_key = get_env_value("GEMINI_API_KEY", dotenv_dict, default="")

        # 4. Categories Taxonomy
        yaml_path = CONFIG_DIR / "categories.yaml"
        categories_list: List[CategoryDefinition] = []
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                raw_cats = content.get("categories", [])
                categories_list = [CategoryDefinition(**c) for c in raw_cats]

        return cls(
            app_env=raw_app_env,
            host=raw_host,
            port=port,
            debug=debug,
            max_image_pixels=max_image_pixels,
            project_root=PROJECT_ROOT,
            data_dir=data_dir,
            thumbnails_dir=thumbnails_dir,
            database_path=database_path,
            enable_gemini_api=enable_gemini,
            gemini_api_key=gemini_key,
            categories=categories_list,
        )


# Singleton instance for easy import across modules
settings = Settings.load()
