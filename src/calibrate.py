"""Close the feedback loop: shrink the adjudicator caps the scorecard shows are HURTING.

Deliberately conservative — shrinkage, not optimisation. A buy-side signal whose forward
alpha where it fired is reliably below where it did NOT (a negative alpha_delta from
scorecard.summarize_by_signal) has its cap pulled toward zero, in proportion to the deficit
and capped at `max_shrink`. It never flips a sign, never amplifies a cap beyond the hand-set
prior, and never touches a signal below the fire-count gate. The result is an overlay file
(config/adjudicator.calibrated.yaml) that config.load_adjudicator applies on top of the
hand-set caps.

WHY conservative: over a short, single-regime ledger, fitting weights to the record just
re-bakes its bias — the exact trap scorecard.py warns about. So the reweight is gated on a
matured-pick floor and is meant to be re-run as the record grows and spans more regimes.
Run: `python -m src.calibrate`  (or `--user` for the packaged install's ledger).
"""
import datetime as dt

from src import config, data, scorecard
from src.profile import Profile

# Attribution note-key (as logged in picks.jsonl `signals`) -> the adjudicator cap it scales.
# Only BUY-side boosts: manufactured upside is the disease behind the inverted top band, and
# shrinking a defensive (negative) cap would make the score *less* cautious — the wrong way.
_SIGNAL_TO_CAP = {
    "catalyst": "catalyst",
    "congress_buy": "congress_buy",
    "insider_buy": "insider_buy",
    "analyst_bull": "analyst",
    "edgar_catalyst": "edgar_catalyst",
    "activist_stake": "activist_stake",
    "options_bull": "options_flow",
    "squeeze_setup": "short_squeeze",
    "estimates_up": "estimate_revision",
    "wsb_buzz": "social",
}

FULL_SHRINK_ALPHA = 2.0   # an alpha deficit of -2% (or worse) triggers the full max_shrink


def compute_calibration(by_signal, base_caps, *, max_shrink=0.5) -> dict:
    """Return {cap_key: shrunk_value} for caps the attribution says are hurting. Pure.

    `by_signal` is scorecard.summarize_by_signal(graded). A signal that helps (alpha_delta >= 0),
    is below the fire gate (`insufficient`), or maps to an unknown cap is left at the prior.
    """
    changes = {}
    for sig_key, cap_key in _SIGNAL_TO_CAP.items():
        stat = by_signal.get(sig_key)
        if not stat or stat.get("insufficient") or stat.get("alpha_delta") is None:
            continue
        delta = stat["alpha_delta"]
        if delta >= 0:
            continue                                   # helps or neutral -> keep the prior
        prior = base_caps.get(cap_key)
        if prior is None:
            continue
        frac = min(1.0, abs(delta) / FULL_SHRINK_ALPHA) * max_shrink
        new = round(prior * (1 - frac), 1)             # toward zero, never past it
        if new != prior:
            changes[cap_key] = new
    return changes


def calibrate(profile: Profile | None = None, *, fetch=None, min_matured=30, write=True) -> dict:
    """Grade the ledger, attribute per-signal alpha, and (only if enough matured picks) write
    the shrinkage overlay. Returns a summary; writes nothing when the sample is too thin."""
    if profile is None:
        profile = Profile.for_repo()
    if fetch is None:
        fetch = data.fetch_history
    graded, _buy_threshold, pick_list = scorecard._grade(profile, fetch)
    matured = [g for g in graded if not g.get("error") and g.get("alpha_5d") is not None]
    by_signal = scorecard.summarize_by_signal(graded)
    base = config.load_adjudicator_base(profile.config_dir)
    if len(matured) < min_matured:
        return {"enough": False, "n_matured": len(matured), "changes": {}, "by_signal": by_signal}
    changes = compute_calibration(by_signal, base)
    if write and changes:
        config.save_calibrated_adjudicator(
            profile.config_dir, {**base, **changes},
            meta={"generated": dt.date.today().isoformat(), "n_matured": len(matured)})
    return {"enough": True, "n_matured": len(matured), "changes": changes, "by_signal": by_signal}


def _print_report(res) -> None:
    if not res["enough"]:
        print(f"Calibration deferred: {res['n_matured']} matured picks (need >= 30). "
              "A short single-regime ledger is noise — let it grow, then re-run.")
        return
    if not res["changes"]:
        print(f"No caps changed: {res['n_matured']} matured picks, but no buy-side signal is "
              "reliably hurting (all alpha deltas >= 0, or below the fire gate).")
        return
    print(f"Calibrated {len(res['changes'])} cap(s) from {res['n_matured']} matured picks:")
    for cap, val in sorted(res["changes"].items()):
        print(f"  {cap} -> {val}")
    print("Wrote config/adjudicator.calibrated.yaml (delete it to revert to hand-set caps).")


if __name__ == "__main__":
    import sys
    if "--user" in sys.argv[1:]:
        from src import apppaths
        _print_report(calibrate(profile=Profile.for_base(apppaths.user_base_dir())))
    else:
        _print_report(calibrate())
