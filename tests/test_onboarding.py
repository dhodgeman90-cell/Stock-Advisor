from src import onboarding, config
from src.profile import Profile


def test_seed_copies_defaults_and_they_load(tmp_path):
    p = Profile.for_base(tmp_path)
    copied = onboarding.seed_profile(p)
    assert set(copied) == {
        "watchlist.yaml", "weights.yaml", "adjudicator.yaml",
        "exits.yaml", "positions.yaml",
    }
    # the seeded files are valid input for the real loaders
    assert config.load_watchlist(p.config_dir)["tickers"]
    assert config.load_weights(p.config_dir)
    assert config.load_adjudicator(p.config_dir)
    assert config.load_exit_rules(p.config_dir)
    assert config.load_positions(p.config_dir) == []


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
