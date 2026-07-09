from src import objectives


def test_balanced_is_identity_for_weights():
    base = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    assert objectives.apply_weights(base, "balanced") == base


def test_balanced_is_identity_for_exits():
    base = {"defaults": {"stop_loss_pct": 5, "trailing_stop_pct": 6},
            "backtest": {"buy_threshold": 65, "max_hold_days": 250}}
    out = objectives.apply_exit_rules(base, "balanced")
    assert out == base
    out["defaults"]["stop_loss_pct"] = 99      # mutating the copy must not touch base
    assert base["defaults"]["stop_loss_pct"] == 5


def test_aggressive_overrides_weights_and_exits():
    base_w = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    w = objectives.apply_weights(base_w, "aggressive")
    assert w["trend"] == 10 and w["pullback"] == 0 and w["breakout"] == 35
    base_x = {"defaults": {"stop_loss_pct": 5, "trailing_stop_pct": 6},
              "backtest": {"buy_threshold": 65, "max_hold_days": 250}}
    x = objectives.apply_exit_rules(base_x, "aggressive")
    # Stops reconciled with the walk-forward sweep (a <10% trail churns out of winners); the
    # aggressive notch is still the tightest but no longer in the pathological range.
    assert x["defaults"]["stop_loss_pct"] == 6
    assert x["defaults"]["trailing_stop_pct"] == 10
    assert x["backtest"]["buy_threshold"] == 55
    assert x["backtest"]["max_hold_days"] == 30


def test_unknown_key_falls_back_to_balanced():
    base = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    assert objectives.normalize("nonsense") == "balanced"
    assert objectives.apply_weights(base, "nonsense") == base


def test_tone_line_only_for_non_balanced():
    assert objectives.tone_line("balanced") is None
    assert isinstance(objectives.tone_line("conservative"), str)


def test_options_in_slider_order():
    keys = [k for k, _ in objectives.options()]
    assert keys == ["conservative", "balanced", "active", "aggressive"]
