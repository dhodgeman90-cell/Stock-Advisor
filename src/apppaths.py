"""Resolve the per-user profile base directory (where THIS user's data lives).

Precedence:
  1. STOCK_ADVISOR_HOME env var  — explicit override (tests, portable installs).
  2. %APPDATA%\\StockAdvisor      — the Windows beta target.
  3. ~/.stockadvisor             — cross-platform fallback (dev on mac/Linux).
The returned dir is NOT created here; the caller seeds it via onboarding.seed_profile.
"""
from __future__ import annotations

import os
from pathlib import Path


def user_base_dir() -> Path:
    override = os.environ.get("STOCK_ADVISOR_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "StockAdvisor"
    return Path.home() / ".stockadvisor"
