from pathlib import Path
from unittest.mock import patch

from photocatalog.viewer.app import _list_subdirs


def test_list_subdirs_returns_sorted_directories(tmp_path: Path):
    (tmp_path / "b_dir").mkdir()
    (tmp_path / "a_dir").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "a_file.txt").write_text("x")

    entries, error = _list_subdirs(tmp_path)

    assert error is None
    assert [e.name for e in entries] == ["a_dir", "b_dir"]


def test_list_subdirs_reports_permission_error(tmp_path: Path):
    with patch.object(Path, "iterdir", side_effect=PermissionError()):
        entries, error = _list_subdirs(tmp_path)

    assert entries == []
    assert error == "Permesso negato per questa cartella."


def test_list_subdirs_reports_other_os_errors(tmp_path: Path):
    with patch.object(Path, "iterdir", side_effect=OSError("disk not readable")):
        entries, error = _list_subdirs(tmp_path)

    assert entries == []
    assert "disk not readable" in error
