"""
Tests for configuration loading, absence of import-time side effects,
and explicit directory initialization (Task B1).
"""

import sys
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from config.settings import settings, Settings
from backend.api.app import app
import scripts.scan as scan_module


def run_import_probe_subprocess(module_to_import: str) -> subprocess.CompletedProcess:
    """
    Spawns a clean Python subprocess that instruments Path.mkdir strictly for
    the configured data and thumbnail directory paths, then imports the module.
    Fails if any target paths are created/attempted during import.
    """
    code = f"""
import sys
from pathlib import Path

# Identify project data and thumbnail targets
project_root = Path.cwd()
target_data = (project_root / "data").resolve()
target_thumbs = (target_data / "thumbnails").resolve()

created_paths = []
original_mkdir = Path.mkdir

def monitored_mkdir(self, *args, **kwargs):
    try:
        resolved = self.resolve()
    except Exception:
        resolved = self
    if resolved == target_data or resolved == target_thumbs or target_data in getattr(resolved, 'parents', ()):
        created_paths.append(str(resolved))
    return original_mkdir(self, *args, **kwargs)

Path.mkdir = monitored_mkdir

try:
    __import__("{module_to_import}")
except Exception as e:
    print(f"IMPORT_ERROR: {{e}}", file=sys.stderr)
    sys.exit(2)

if created_paths:
    print(f"SIDE_EFFECTS: {{created_paths}}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
"""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(settings.project_root)
    )


def test_import_config_settings_has_no_filesystem_side_effects():
    """
    Verifies that importing config.settings in a fresh Python process
    does not create or attempt to create data or thumbnails directories.
    """
    proc = run_import_probe_subprocess("config.settings")
    assert proc.returncode == 0, f"Importing config.settings produced side effects: {proc.stderr}"


def test_import_backend_api_app_has_no_filesystem_side_effects():
    """
    Verifies that importing backend.api.app in a fresh Python process
    does not create or attempt to create data or thumbnails directories.
    """
    proc = run_import_probe_subprocess("backend.api.app")
    assert proc.returncode == 0, f"Importing backend.api.app produced side effects: {proc.stderr}"


def test_import_scripts_scan_has_no_filesystem_side_effects():
    """
    Verifies that importing scripts.scan in a fresh Python process
    does not create or attempt to create data or thumbnails directories.
    """
    proc = run_import_probe_subprocess("scripts.scan")
    assert proc.returncode == 0, f"Importing scripts.scan produced side effects: {proc.stderr}"


def test_settings_ensure_directories_creates_paths_and_is_idempotent(tmp_path: Path):
    """
    Verifies that Settings.ensure_directories() creates both data_dir and
    thumbnails_dir when called explicitly, and is safe to call repeatedly.
    """
    custom_data = tmp_path / "custom_data"
    custom_thumbs = custom_data / "custom_thumbs"

    test_settings = Settings(
        project_root=tmp_path,
        data_dir=custom_data,
        thumbnails_dir=custom_thumbs,
        database_path=custom_data / "test.db",
    )

    assert not custom_data.exists()
    assert not custom_thumbs.exists()

    # Must have the method and execute cleanly
    assert hasattr(test_settings, "ensure_directories"), "Settings missing ensure_directories method"
    test_settings.ensure_directories()

    assert custom_data.is_dir()
    assert custom_thumbs.is_dir()

    # Idempotency check: calling again must not raise any error
    test_settings.ensure_directories()
    assert custom_data.is_dir()
    assert custom_thumbs.is_dir()


def test_fastapi_lifespan_initializes_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that the FastAPI lifespan handler calls explicit directory
    initialization on server startup when entered via TestClient context manager.
    Redirects directory paths to tmp_path to avoid touching production data.
    """
    test_data = tmp_path / "app_data"
    test_thumbs = test_data / "thumbnails"

    monkeypatch.setattr(settings, "data_dir", test_data)
    monkeypatch.setattr(settings, "thumbnails_dir", test_thumbs)

    assert not test_data.exists()
    assert not test_thumbs.exists()

    # Entering TestClient context runs FastAPI lifespan startup
    with TestClient(app) as client:
        assert test_data.is_dir(), "FastAPI lifespan did not initialize data_dir"
        assert test_thumbs.is_dir(), "FastAPI lifespan did not initialize thumbnails_dir"

        # Verify API is functional inside lifespan
        resp = client.get("/api/health")
        assert resp.status_code == 200


def test_cli_scan_invokes_explicit_initialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that scripts/scan.py invokes explicit initialization before
    initiating database or directory scanning work.
    """
    calls = []

    def mock_ensure_directories(self=None):
        calls.append("ensure_directories")

    monkeypatch.setattr(Settings, "ensure_directories", mock_ensure_directories, raising=False)

    # Mock init_db and scan_directory to capture ordering and prevent real execution
    def mock_init_db(*args, **kwargs):
        calls.append("init_db")

    def mock_scan_directory(*args, **kwargs):
        calls.append("scan_directory")
        from backend.core.scanner import ScanProgress
        return ScanProgress(is_complete=True)

    monkeypatch.setattr(scan_module, "init_db", mock_init_db)
    monkeypatch.setattr(scan_module, "scan_directory", mock_scan_directory)
    monkeypatch.setattr(sys, "argv", ["scan.py", str(tmp_path)])

    scan_module.main()

    assert "ensure_directories" in calls, "scripts/scan.py did not call ensure_directories()"
    assert calls.index("ensure_directories") < calls.index("init_db"), (
        "ensure_directories must be invoked before init_db"
    )


# =============================================================================
# Task B2: Environment Configuration Loading Tests
# =============================================================================

def test_settings_load_defaults(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that when no process environment variables or .env overrides are present,
    Settings.load() returns exact built-in defaults.
    """
    # Clear any potential environment variables
    for key in ["DATA_DIR", "THUMBNAILS_DIR", "DATABASE_PATH", "APP_ENV", "HOST", "PORT", "DEBUG", "MAX_IMAGE_PIXELS", "ENABLE_GEMINI_API", "GEMINI_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    assert loaded.data_dir == (loaded.project_root / "data").resolve()
    assert loaded.thumbnails_dir == (loaded.data_dir / "thumbnails").resolve()
    assert loaded.database_path == (loaded.data_dir / "gallery.db").resolve()
    assert loaded.app_env == "development"
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8000
    assert loaded.debug is True
    assert loaded.max_image_pixels == 89_478_485
    assert loaded.enable_gemini_api is False
    assert loaded.gemini_api_key == ""


def test_settings_load_custom_data_dir_and_default_subpaths(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that setting DATA_DIR customizes data_dir and causes thumbnails_dir
    and database_path to automatically default inside the custom data_dir.
    """
    monkeypatch.setenv("DATA_DIR", "my_custom_store")
    monkeypatch.delenv("THUMBNAILS_DIR", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    expected_data = (loaded.project_root / "my_custom_store").resolve()
    assert loaded.data_dir == expected_data
    assert loaded.thumbnails_dir == expected_data / "thumbnails"
    assert loaded.database_path == expected_data / "gallery.db"


def test_settings_load_empty_or_whitespace_path_overrides_treated_as_unset(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that empty or whitespace-only overrides for optional paths
    fall back to data_dir defaults without raising errors.
    """
    monkeypatch.setenv("DATA_DIR", "clean_store")
    monkeypatch.setenv("THUMBNAILS_DIR", "   ")
    monkeypatch.setenv("DATABASE_PATH", "")

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    expected_data = (loaded.project_root / "clean_store").resolve()
    assert loaded.data_dir == expected_data
    assert loaded.thumbnails_dir == expected_data / "thumbnails"
    assert loaded.database_path == expected_data / "gallery.db"


def test_settings_load_independent_path_overrides(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that explicit THUMBNAILS_DIR and DATABASE_PATH overrides
    take precedence over data_dir subpaths.
    """
    monkeypatch.setenv("DATA_DIR", "root_data")
    monkeypatch.setenv("THUMBNAILS_DIR", "independent_thumbs")
    monkeypatch.setenv("DATABASE_PATH", "databases/custom_catalog.db")

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    assert loaded.data_dir == (loaded.project_root / "root_data").resolve()
    assert loaded.thumbnails_dir == (loaded.project_root / "independent_thumbs").resolve()
    assert loaded.database_path == (loaded.project_root / "databases" / "custom_catalog.db").resolve()


def test_settings_load_absolute_path_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that absolute path overrides are preserved accurately.
    """
    abs_data = (tmp_path / "absolute_data").resolve()
    abs_thumbs = (tmp_path / "absolute_thumbs").resolve()
    abs_db = (tmp_path / "dbs" / "gallery.db").resolve()

    monkeypatch.setenv("DATA_DIR", str(abs_data))
    monkeypatch.setenv("THUMBNAILS_DIR", str(abs_thumbs))
    monkeypatch.setenv("DATABASE_PATH", str(abs_db))

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    assert loaded.data_dir == abs_data
    assert loaded.thumbnails_dir == abs_thumbs
    assert loaded.database_path == abs_db


def test_settings_load_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that Settings.load(env_file=...) parses configuration values
    from a specified .env file when process environment variables are unset.
    """
    for key in ["DATA_DIR", "PORT", "DEBUG", "MAX_IMAGE_PIXELS", "HOST"]:
        monkeypatch.delenv(key, raising=False)

    env_path = tmp_path / "custom.env"
    env_path.write_text(
        "DATA_DIR=dotenv_data_dir\n"
        "PORT=9090\n"
        "DEBUG=false\n"
        "MAX_IMAGE_PIXELS=40000000\n"
        "HOST=0.0.0.0\n",
        encoding="utf-8"
    )

    loaded = Settings.load(env_file=env_path)

    assert loaded.data_dir == (loaded.project_root / "dotenv_data_dir").resolve()
    assert loaded.port == 9090
    assert loaded.debug is False
    assert loaded.max_image_pixels == 40_000_000
    assert loaded.host == "0.0.0.0"


def test_configuration_precedence_process_env_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that process environment variables take strict precedence over .env file entries,
    and missing values fall back to defaults (Process Env > .env > Defaults).
    """
    env_path = tmp_path / "precedence.env"
    env_path.write_text(
        "PORT=8000\n"
        "DATA_DIR=from_dotenv\n"
        "DEBUG=true\n",
        encoding="utf-8"
    )

    # Process environment overrides PORT and DEBUG, but leaves DATA_DIR to .env
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.delenv("DATA_DIR", raising=False)

    loaded = Settings.load(env_file=env_path)

    assert loaded.port == 9999  # From process env (wins over dotenv's 8000)
    assert loaded.debug is False  # From process env (wins over dotenv's true)
    assert loaded.data_dir == (loaded.project_root / "from_dotenv").resolve()  # From dotenv


def test_settings_load_invalid_port_raises_value_error(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that non-integer, non-positive, or out-of-range PORT values
    raise clear, actionable ValueErrors.
    """
    for invalid_port in ["not_a_number", "0", "-5", "65536", "100000"]:
        monkeypatch.setenv("PORT", invalid_port)
        with pytest.raises(ValueError, match=r"(?i)invalid port"):
            Settings.load(env_file=Path("non_existent_env_file.env"))


def test_settings_load_invalid_max_pixels_raises_value_error(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that non-integer or non-positive MAX_IMAGE_PIXELS values
    raise clear, actionable ValueErrors.
    """
    for invalid_pixels in ["not_an_int", "0", "-1000", "3.14"]:
        monkeypatch.setenv("MAX_IMAGE_PIXELS", invalid_pixels)
        with pytest.raises(ValueError, match=r"(?i)invalid max_image_pixels"):
            Settings.load(env_file=Path("non_existent_env_file.env"))


def test_settings_load_invalid_boolean_raises_value_error(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that unsupported boolean values for DEBUG or ENABLE_GEMINI_API
    raise clear, actionable ValueErrors.
    """
    monkeypatch.setenv("DEBUG", "not_a_boolean")
    with pytest.raises(ValueError, match=r"(?i)invalid boolean value for debug"):
        Settings.load(env_file=Path("non_existent_env_file.env"))

    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("ENABLE_GEMINI_API", "maybe")
    with pytest.raises(ValueError, match=r"(?i)invalid boolean value for enable_gemini_api"):
        Settings.load(env_file=Path("non_existent_env_file.env"))


def test_settings_load_has_no_filesystem_side_effects(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that Settings.load() with custom non-existent directory paths
    computes paths in memory without creating the directories on disk.
    """
    fake_data_name = "test_transient_never_created_dir_9999"
    target_path = Settings(project_root=Path.cwd()).project_root / fake_data_name

    monkeypatch.setenv("DATA_DIR", fake_data_name)

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    assert loaded.data_dir == target_path.resolve()
    assert not target_path.exists(), "Settings.load() must not create directories"


def test_gemini_configuration_preserved(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that existing Gemini API configuration (ENABLE_GEMINI_API, GEMINI_API_KEY)
    is loaded correctly and preserved.
    """
    monkeypatch.setenv("ENABLE_GEMINI_API", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic_test_gemini_key_456")

    loaded = Settings.load(env_file=Path("non_existent_env_file.env"))

    assert loaded.enable_gemini_api is True
    assert loaded.gemini_api_key == "synthetic_test_gemini_key_456"
