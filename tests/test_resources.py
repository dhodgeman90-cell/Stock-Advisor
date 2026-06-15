from src import resources


def test_base_path_is_repo_root_in_dev():
    # In dev (not frozen) base_path() is the repo root that contains the src package.
    assert (resources.base_path() / "src" / "profile.py").exists()


def test_defaults_and_ui_dirs_hang_off_base():
    assert resources.defaults_dir() == resources.base_path() / "defaults"
    assert resources.ui_dir() == resources.base_path() / "ui"
