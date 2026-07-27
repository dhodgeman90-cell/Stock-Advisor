"""Objective presets ("risk slider"): named bundles that retune scoring weights and
exit rules without the user editing YAML. Applied in-memory at run time, so the user's
config files stay pristine and switching presets is non-destructive.

`balanced` is the IDENTITY preset — it applies no overrides, so it always reproduces
exactly what the user's weights.yaml / exits.yaml already do. That is the migration
guarantee: existing users default to balanced and see no behavior change.
"""
from __future__ import annotations

import copy

DEFAULT = "balanced"
ORDER = ["conservative", "balanced", "active", "aggressive"]   # slider order

OBJECTIVES = {
    # Stop/trail widths reconciled with the 2026-07-09 walk-forward sweep: a trailing stop
    # below ~10% churns out of every winner on a routine pullback and destroys returns without
    # reducing drawdown. The slider stays monotonic (conservative widest -> aggressive tightest),
    # but every notch now sits in the validated, non-pathological range.
    "conservative": {
        "label": "Conservative",
        "weights": {"breakout": 15, "volume": 20, "momentum": 10, "trend": 40, "pullback": 15},
        "stop_loss_pct": 10, "trailing_stop_pct": 25,
        "max_hold_days": 250, "buy_threshold": 75,
        "tone_line": "Conservative lens · trend-led, fewer high-conviction moves, widest stops.",
    },
    "balanced": {
        "label": "Balanced",
        "weights": None,            # identity: use the user's config as-is
        "stop_loss_pct": None, "trailing_stop_pct": None,
        "max_hold_days": None, "buy_threshold": None,
        "tone_line": None,
    },
    "active": {
        "label": "Active",
        "weights": {"breakout": 32, "volume": 30, "momentum": 23, "trend": 12, "pullback": 3},
        "stop_loss_pct": 7, "trailing_stop_pct": 14,
        "max_hold_days": 90, "buy_threshold": 60,
        "tone_line": "Active lens · momentum-tilted with shorter holds.",
    },
    "aggressive": {
        "label": "Aggressive Swing",
        "weights": {"breakout": 35, "volume": 30, "momentum": 25, "trend": 10, "pullback": 0},
        "stop_loss_pct": 6, "trailing_stop_pct": 10,
        "max_hold_days": 30, "buy_threshold": 55,
        "tone_line": "Aggressive Swing lens · momentum-led, tighter stops, short holds.",
    },
}


def normalize(key) -> str:
    return key if key in OBJECTIVES else DEFAULT


def get(key) -> dict:
    return OBJECTIVES[normalize(key)]


def apply_weights(base_weights: dict, key) -> dict:
    preset = get(key)
    if preset["weights"] is None:
        return dict(base_weights)
    return {k: float(v) for k, v in preset["weights"].items()}


def apply_exit_rules(base_rules: dict, key) -> dict:
    """Return a deep copy of base_rules with the preset's exit overrides applied.
    Only the four knobs the slider owns are touched; everything else is preserved."""
    preset = get(key)
    rules = copy.deepcopy(base_rules)
    if preset["stop_loss_pct"] is not None:
        rules["defaults"]["stop_loss_pct"] = preset["stop_loss_pct"]
    if preset["trailing_stop_pct"] is not None:
        rules["defaults"]["trailing_stop_pct"] = preset["trailing_stop_pct"]
    if preset["buy_threshold"] is not None:
        rules["backtest"]["buy_threshold"] = preset["buy_threshold"]
    if preset["max_hold_days"] is not None:
        # BOTH dicts: exits.evaluate_exit reads defaults["max_hold_days"] for the LIVE
        # time-stop, while simulate_ticker reads backtest["max_hold_days"] for its bar-based
        # force-close. Writing only the backtest key made the slider's holding period a
        # backtest-only knob — "Aggressive" (30 days) still held live positions for 180.
        rules["defaults"]["max_hold_days"] = preset["max_hold_days"]
        rules["backtest"]["max_hold_days"] = preset["max_hold_days"]
    return rules


def tone_line(key):
    return get(key)["tone_line"]


def options() -> list:
    """[(key, label)] in slider order, for the settings UI."""
    return [(k, OBJECTIVES[k]["label"]) for k in ORDER]
