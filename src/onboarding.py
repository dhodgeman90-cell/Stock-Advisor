"""First-run setup for a fresh per-user profile.

seed_profile() copies the bundled default configs into the profile's config dir,
but only the ones that don't exist yet — so it is safe to call on every launch and
never overwrites a user's edits. Disclaimer acceptance is stored in a small JSON
state file inside the profile so the welcome screen shows exactly once.
"""
from __future__ import annotations

import json
import shutil

from src import resources

# Keep in sync with config/ — tests/test_onboarding.py asserts the seeded exit rules equal
# the repo's. A packaged profile seeds from here ONCE and never re-syncs, so anything stale
# in defaults/ becomes a permanent setting for every installed user. That is how the
# pathological 5%/6% stops (and a missing max_hold_days, which resolves to 0 and disables
# the live time-stop entirely) shipped while config/ carried the tuned 8%/20%.
DEFAULT_FILES = [
    "watchlist.yaml",
    "weights.yaml",
    "adjudicator.yaml",
    "exits.yaml",
    "positions.yaml",
    "signals.yaml",
    "universe.txt",     # without this the installed app scans 10 names, not 586
]


def seed_profile(profile) -> list:
    """Copy any missing default config into profile.config_dir. Returns the names
    actually copied (empty on an already-seeded profile)."""
    profile.ensure_dirs()
    src_dir = resources.defaults_dir()
    copied = []
    for name in DEFAULT_FILES:
        dest = profile.config_dir / name
        if not dest.exists():
            shutil.copyfile(src_dir / name, dest)
            copied.append(name)
    return copied


def _state_path(profile):
    return profile.config_dir / "app_state.json"


def _load_state(profile) -> dict:
    path = _state_path(profile)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def disclaimer_accepted(profile) -> bool:
    return bool(_load_state(profile).get("disclaimer_accepted"))


def accept_disclaimer(profile) -> None:
    profile.ensure_dirs()
    state = _load_state(profile)
    state["disclaimer_accepted"] = True
    _state_path(profile).write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_objective(profile) -> str:
    from src import objectives
    return objectives.normalize(_load_state(profile).get("objective"))


def set_objective(profile, key) -> None:
    from src import objectives
    profile.ensure_dirs()
    state = _load_state(profile)
    state["objective"] = objectives.normalize(key)
    _state_path(profile).write_text(json.dumps(state, indent=2), encoding="utf-8")
