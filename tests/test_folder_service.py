"""
Tests for Folder Service: validation, path safety, overlap checking, and explorer opening.
"""

from pathlib import Path
import pytest
from unittest.mock import patch

from backend.core.folder_service import (
    validate_local_folder,
    check_folder_overlap,
    open_in_file_explorer,
)


def test_validate_local_folder_success(tmp_path: Path):
    """Verifies that an existing absolute directory path is validated."""
    resolved = validate_local_folder(str(tmp_path), must_exist=True)
    assert resolved == tmp_path.resolve()


def test_validate_local_folder_nonexistent_fails(tmp_path: Path):
    """Verifies that a nonexistent directory raises ValueError when must_exist=True."""
    bad_path = tmp_path / "does_not_exist"
    with pytest.raises(ValueError, match="does not exist"):
        validate_local_folder(str(bad_path), must_exist=True)


def test_validate_local_folder_can_create_destination(tmp_path: Path):
    """Verifies that destination folders that do not exist yet are accepted when must_exist=False."""
    new_dest = tmp_path / "new_organized_output"
    resolved = validate_local_folder(str(new_dest), must_exist=False)
    assert resolved == new_dest.resolve()


def test_validate_local_folder_rejects_empty_or_relative():
    """Verifies that blank or non-absolute paths are rejected."""
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_local_folder("", must_exist=False)

    with pytest.raises(ValueError, match="must be an absolute"):
        validate_local_folder("relative/folder", must_exist=False)


def test_check_folder_overlap(tmp_path: Path):
    """Verifies that destination inside source tree is detected as overlap."""
    source = tmp_path / "photos"
    source.mkdir()

    # Destination inside source
    dest_inside = source / "Organized"
    assert check_folder_overlap(source, dest_inside) is True

    # Same folder
    assert check_folder_overlap(source, source) is True

    # Separate folder
    dest_separate = tmp_path / "Organized_Photos"
    dest_separate.mkdir()
    assert check_folder_overlap(source, dest_separate) is False


def test_open_in_file_explorer_triggers_system_call(tmp_path: Path):
    """Verifies open_in_file_explorer calls Windows explorer safely."""
    with patch("subprocess.Popen") as mock_popen:
        success = open_in_file_explorer(str(tmp_path))
        assert success is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "explorer.exe" in args
        assert str(tmp_path.resolve()) in args
