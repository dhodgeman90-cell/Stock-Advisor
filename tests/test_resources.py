import sys

from src import resources


def test_base_path_is_repo_root_in_dev():
    # In dev (not frozen) base_path() is the repo root that contains the src package.
    assert (resources.base_path() / "src" / "profile.py").exists()


def test_defaults_and_ui_dirs_hang_off_base():
    assert resources.defaults_dir() == resources.base_path() / "defaults"
    assert resources.ui_dir() == resources.base_path() / "ui"


def test_base_path_uses_meipass_when_frozen(monkeypatch, tmp_path):
    # PyInstaller sets sys._MEIPASS at runtime; base_path() must follow it (Plan 3
    # relies on this so defaults/ + ui/ resolve inside the bundle).
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.base_path() == tmp_path
    assert resources.defaults_dir() == tmp_path / "defaults"
    assert resources.ui_dir() == tmp_path / "ui"
