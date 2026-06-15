"""Locate bundled, read-only resources (default configs + the static UI).

In development these live in the repo. Under a PyInstaller build, files added with
--add-data are unpacked to sys._MEIPASS at runtime. base_path() returns the right
root for both, so callers never branch on "are we frozen?" — Plan 3 only has to map
defaults/ and ui/ into the bundle; this module is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path


def base_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent   # repo root (parent of src/)


def defaults_dir() -> Path:
    return base_path() / "defaults"


def ui_dir() -> Path:
    return base_path() / "ui"
