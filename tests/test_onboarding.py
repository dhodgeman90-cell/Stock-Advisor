from pathlib import Path

from src import onboarding, config, resources
from src.profile import Profile

REPO_CONFIG = Path(__file__).resolve().parent.parent / "config"


def test_seed_copies_defaults_and_they_load(tmp_path):
    p = Profile.for_base(tmp_path)
    copied = onboarding.seed_profile(p)
    assert set(copied) == {
        "watchlist.yaml", "weights.yaml", "adjudicator.yaml",
        "exits.yaml", "positions.yaml", "signals.yaml", "universe.txt",
    }
    # the seeded files are valid input for the real loaders
    assert config.load_watchlist(p.config_dir)["tickers"]
    assert config.load_weights(p.config_dir)
    assert config.load_adjudicator(p.config_dir)
    assert config.load_exit_rules(p.config_dir)
    assert config.load_positions(p.config_dir) == []


# ---- defaults must not drift from the tuned repo config ------------------
# The installed app seeds from defaults/ and never re-syncs. Before this, a packaged
# profile shipped stop_loss_pct 5 / trailing_stop_pct 6 — the values config/exits.yaml's
# own header calls pathological (24.8% vs 42.4% compounded on the shipped tickers) —
# and omitted max_hold_days entirely, which resolves to 0 and disables the live
# time-stop at every risk-slider notch. It also shipped no universe.txt, so the
# installed app scanned 10 names instead of 586.

def test_seeded_exit_rules_match_the_repo_config(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    assert config.load_exit_rules(p.config_dir) == config.load_exit_rules(REPO_CONFIG)


def test_defaults_never_ship_the_pathological_stops(tmp_path):
    d = config.load_exit_rules(resources.defaults_dir())["defaults"]
    assert d["stop_loss_pct"] >= 8, "the 5% stop churned out of every winner"
    assert d["trailing_stop_pct"] >= 20, "the 6% trail was the main return leak"
    assert d.get("max_hold_days"), "missing max_hold_days silently disables the live time-stop"


def test_seeded_profile_scans_the_broad_universe_not_just_the_watchlist(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    universe = config.load_universe(p.config_dir)
    assert universe and len(universe) > 100


def test_seeded_profile_starts_with_buys_paused(tmp_path):
    # A brand-new install must not hand out buy calls from an unvalidated engine.
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    assert config.load_watchlist(p.config_dir)["settings"].get("adds_paused") is True


def test_seed_is_idempotent_and_nondestructive(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    config.save_watchlist(p.config_dir, ["ZZZZ"], {"shortlist_size": 1})  # user edits
    copied = onboarding.seed_profile(p)                                   # second run
    assert copied == []                                                   # nothing re-copied
    assert config.load_watchlist(p.config_dir)["tickers"] == ["ZZZZ"]     # not clobbered


def test_disclaimer_state_roundtrip(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    assert onboarding.disclaimer_accepted(p) is False
    onboarding.accept_disclaimer(p)
    assert onboarding.disclaimer_accepted(p) is True


def test_objective_defaults_to_balanced(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    assert onboarding.get_objective(p) == "balanced"


def test_objective_roundtrip_and_preserves_disclaimer(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.accept_disclaimer(p)
    onboarding.set_objective(p, "aggressive")
    assert onboarding.get_objective(p) == "aggressive"
    assert onboarding.disclaimer_accepted(p) is True   # not clobbered


def test_objective_rejects_garbage(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    onboarding.set_objective(p, "nonsense")
    assert onboarding.get_objective(p) == "balanced"
