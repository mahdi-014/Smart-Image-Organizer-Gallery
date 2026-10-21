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
