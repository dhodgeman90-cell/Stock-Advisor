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
    """Secret/config lookup with a fixed precedence. For the per-user app the order is
    OS credential store -> integrations.yaml config -> profile .env -> process env. For
    the owner's repo profile, keyring_service is None and config_values is empty, so it
    degrades to the original .env -> process-env behavior (owner CLI unchanged).

    apply_to_environ() pushes the resolved values into os.environ (without clobbering
    existing vars) for the downstream modules (broker, llm, congress) that read
    os.environ directly.
    """

    def __init__(self, dotenv_path: Optional[Path] = None, values: Optional[dict] = None,
                 *, keyring_service: Optional[str] = None, config_values: Optional[dict] = None):
        self._dotenv_path = Path(dotenv_path) if dotenv_path else None
        if values is not None:
            self._values = dict(values)
        else:
            self._values = self._read_dotenv(self._dotenv_path)
        self._keyring_service = keyring_service
        self._config_values = dict(config_values or {})
        self._applied_keys: set = set()   # feature keys THIS instance pushed into os.environ

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

    def update_config_values(self, mapping: dict) -> None:
        """Replace the in-memory non-secret config layer (after the user edits it via
        the API), so the change takes effect without restarting the server."""
        self._config_values = dict(mapping or {})

    def _managed_keys(self) -> tuple:
        """Feature-owned keys whose authoritative source is the OS credential store /
        integrations config. Empty for the owner's repo profile (keyring_service=None),
        so that profile's behavior is completely unchanged."""
        if self._keyring_service is None:
            return ()
        from src import secrets_store
        from src import config as _config
        return (*secrets_store.SECRET_KEYS, *_config.INTEGRATION_FIELDS)

    def _resolve_from_sources(self, key: str):
        """Resolve keyring -> integrations config -> profile .env. Deliberately EXCLUDES
        os.environ (which is apply_to_environ's write sink) so it never returns a value
        this instance previously pushed there."""
        if self._keyring_service is not None:
            from src import secrets_store
            if key in secrets_store.SECRET_KEYS:
                kv = secrets_store.get_secret(key)
                if kv:
                    return kv
        cv = self._config_values.get(key)
        if cv is not None and cv != "":
            return cv
        val = self._values.get(key)
        if val is not None and val != "":
            return val
        return None

    def get(self, key: str, default=None):
        resolved = self._resolve_from_sources(key)
        if resolved is not None:
            return resolved
        return os.environ.get(key, default)

    def apply_to_environ(self) -> None:
        # Feature-owned keys are kept AUTHORITATIVE in os.environ: push the freshly
        # resolved value (so a rotation takes effect) and remove a value THIS instance
        # previously pushed once it has been cleared (so a long-lived server process stops
        # exporting a secret the user deleted). Ambient vars we never set are left alone.
        managed = self._managed_keys()
        for key in managed:
            resolved = self._resolve_from_sources(key)
            if resolved is not None and resolved != "":
                os.environ[key] = str(resolved)
                self._applied_keys.add(key)
            elif key in self._applied_keys:
                os.environ.pop(key, None)
                self._applied_keys.discard(key)
        # Non-feature .env values keep the original back-compat behavior (owner CLI path):
        # set only when absent, never clobber an existing/ambient var.
        managed_set = set(managed)
        for key, val in self._values.items():
            if val != "" and key not in managed_set:
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
        """Per-user profile rooted at an arbitrary base dir (e.g. %APPDATA%/StockAdvisor).

        Enables the OS credential store (for the two secret keys) and loads the
        non-secret email config from integrations.yaml. The owner's repo profile
        (for_repo) deliberately does NOT enable these."""
        from src import config as _config
        from src import secrets_store
        base = Path(base)
        config_dir = base / "config"
        return cls(
            config_dir=config_dir,
            data_dir=base / "data",
            reports_dir=base / "reports",
            secrets=EnvSecrets(
                dotenv_path=base / ".env",
                keyring_service=secrets_store.SERVICE,
                config_values=_config.load_integrations(config_dir),
            ),
        )

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.data_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)
