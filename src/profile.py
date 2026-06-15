"""Per-run identity: which config/data/reports dirs and secret source to use.

The engine was originally hard-wired to repo-relative paths and a repo-level .env
(one machine, one owner). `Profile` makes "whose run is this?" an explicit input so
the same engine can serve a packaged per-user install whose data lives in, e.g.,
%APPDATA%\\StockAdvisor — without the owner's files ever shipping inside the app.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class EnvSecrets:
    """Secret lookup with a fixed precedence: profile .env file, then process env.

    Values are read once at construction from the .env file (if present) into an
    in-memory dict. `.get()` checks that dict first, then os.environ, so an explicit
    profile secret wins over an ambient one. `.apply_to_environ()` pushes the file
    values into os.environ (without clobbering existing vars) for the downstream
    modules (broker, llm, congress) that still read os.environ directly —
    reproducing today's load_dotenv() behavior.
    """

    def __init__(self, dotenv_path: Optional[Path] = None, values: Optional[dict] = None):
        self._dotenv_path = Path(dotenv_path) if dotenv_path else None
        if values is not None:
            self._values = dict(values)
        else:
            self._values = self._read_dotenv(self._dotenv_path)

    @staticmethod
    def _read_dotenv(path: Optional[Path]) -> dict:
        if not path or not path.exists():
            return {}
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
        return out

    def get(self, key: str, default=None):
        val = self._values.get(key)
        if val is not None and val != "":
            return val
        return os.environ.get(key, default)

    def apply_to_environ(self) -> None:
        for key, val in self._values.items():
            if val != "":
                os.environ.setdefault(key, val)
