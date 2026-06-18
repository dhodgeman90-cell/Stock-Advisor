"""Thin wrapper over the OS credential store (via the `keyring` library).

On Windows this is the Credential Manager (DPAPI-backed) — no extra install.
The per-user app stores a small set of secrets here (SECRET_KEYS); everything else
is non-secret config. The backend is swappable (set_backend) so tests use an
in-memory fake and never touch the real credential store. All reads degrade to
None if no backend is available, so a missing credential store never crashes a run.
"""
from __future__ import annotations

SERVICE = "StockAdvisor"
SECRET_KEYS = ("ANTHROPIC_API_KEY", "EMAIL_PASSWORD",
               "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_USER_SECRET")

_backend = None


def set_backend(backend) -> None:
    """Override the keyring backend (tests inject an in-memory fake)."""
    global _backend
    _backend = backend


def _get_backend():
    global _backend
    if _backend is None:
        import keyring
        _backend = keyring
    return _backend


def get_secret(key: str):
    try:
        # `or None` normalises keyring's missing-key return and treats a stored empty string as absent
        return _get_backend().get_password(SERVICE, key) or None
    except Exception:
        return None


def set_secret(key: str, value: str) -> None:
    _get_backend().set_password(SERVICE, key, value)


def delete_secret(key: str) -> None:
    try:
        _get_backend().delete_password(SERVICE, key)
    except Exception:
        pass   # deleting an unset secret is a no-op


def has_secret(key: str) -> bool:
    return get_secret(key) is not None
