"""Per-run identity: which config/data/reports dirs and secret source to use.

The engine was originally hard-wired to repo-relative paths and a repo-level .env
(one machine, one owner). `Profile` makes "whose run is this?" an explicit input so
the same engine can serve a packaged per-user install whose data lives in, e.g.,
%APPDATA%\\StockAdvisor — without the owner's files ever shipping inside the app.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


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
        # Delegate to python-dotenv (already a required dependency, also used by
        # link_broker.py) for robust parsing: it correctly handles `export ` prefixes,
        # inline `# comments`, and quoting that a hand-rolled splitter gets wrong.
        # interpolate=False keeps secrets literal — a value containing `$` is never
        # expanded as a ${VAR} reference. None values (bare `KEY` with no `=`) are
        # dropped so only real values are stored.
        if not path or not path.exists():
            return {}
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(path, interpolate=False, encoding="utf-8").items()
                if v is not None}

    def get(self, key: str, default=None):
        val = self._values.get(key)
        if val is not None and val != "":
            return val
        return os.environ.get(key, default)

    def apply_to_environ(self) -> None:
        for key, val in self._values.items():
            if val != "":
                os.environ.setdefault(key, val)


@dataclass(frozen=True)
class Profile:
    config_dir: Path
    data_dir: Path
    reports_dir: Path
    secrets: EnvSecrets

    @classmethod
    def for_repo(cls) -> "Profile":
        """Owner's personal profile: repo-relative dirs + repo .env (back-compat)."""
        return cls(
            config_dir=ROOT / "config",
            data_dir=ROOT / "data",
            reports_dir=ROOT / "reports",
            secrets=EnvSecrets(dotenv_path=ROOT / ".env"),
        )

    @classmethod
    def for_base(cls, base) -> "Profile":
        """Per-user profile rooted at an arbitrary base dir (e.g. %APPDATA%/StockAdvisor)."""
        base = Path(base)
        return cls(
            config_dir=base / "config",
            data_dir=base / "data",
            reports_dir=base / "reports",
            secrets=EnvSecrets(dotenv_path=base / ".env"),
        )

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.data_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)
