"""Phase D — calibration shrinkage math and the adjudicator overlay round-trip."""
from src import calibrate, config

BASE = {"catalyst": 15, "congress_buy": 18, "analyst": 8, "options_flow": 8,
        "short_squeeze": 10, "estimate_revision": 5, "insider_buy": 12,
        "activist_stake": 12, "edgar_catalyst": 15, "social": 10, "risk_high": 20}


def _sig(alpha_delta, n=40, insufficient=False):
    return {"alpha_delta": alpha_delta, "n_fired": n, "insufficient": insufficient}


def test_negative_alpha_shrinks_the_cap():
    # congress_buy fired with -2% alpha vs not-fired -> full 50% shrink of its 18-pt cap.
    changes = calibrate.compute_calibration({"congress_buy": _sig(-2.0)}, BASE)
    assert changes["congress_buy"] == 9.0            # 18 * (1 - 0.5)


def test_small_deficit_shrinks_proportionally():
    # -1% deficit -> half of max_shrink (0.25) -> 15 * 0.75 = 11.25 -> 11.2 (rounded 1dp).
    changes = calibrate.compute_calibration({"catalyst": _sig(-1.0)}, BASE)
    assert changes["catalyst"] == 11.2


def test_positive_alpha_leaves_cap_untouched():
    assert calibrate.compute_calibration({"congress_buy": _sig(+1.5)}, BASE) == {}


def test_insufficient_sample_is_untouched():
    assert calibrate.compute_calibration(
        {"congress_buy": _sig(-3.0, n=5, insufficient=True)}, BASE) == {}


def test_shrink_never_goes_negative_or_exceeds_prior():
    # 'analyst_bull' is the attribution note-key; it scales the 'analyst' cap.
    changes = calibrate.compute_calibration({"analyst_bull": _sig(-10.0)}, BASE)   # huge deficit
    assert 0 <= changes["analyst"] <= BASE["analyst"]     # clamped by max_shrink, never < 0


def test_only_mapped_buy_side_signals_are_calibrated():
    # a defensive/negative note key is not in the buy-side map -> never shrunk here.
    assert calibrate.compute_calibration({"risk_high": _sig(-2.0)}, BASE) == {}


# ---- config overlay round-trip -------------------------------------------
def test_overlay_applied_on_top_of_base(tmp_path):
    (tmp_path / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  congress_buy: 18\n  analyst: 8\n", encoding="utf-8")
    assert config.load_adjudicator(tmp_path)["congress_buy"] == 18   # no overlay yet

    config.save_calibrated_adjudicator(tmp_path, {"congress_buy": 9.0},
                                       meta={"n_matured": 40})
    caps = config.load_adjudicator(tmp_path)
    assert caps["congress_buy"] == 9.0        # overlay wins
    assert caps["catalyst"] == 15             # untouched cap keeps the prior
    # base loader still sees the hand-set prior (so re-calibration shrinks from 18, not 9)
    assert config.load_adjudicator_base(tmp_path)["congress_buy"] == 18


def test_overlay_ignores_unknown_caps(tmp_path):
    (tmp_path / "adjudicator.yaml").write_text("caps:\n  catalyst: 15\n", encoding="utf-8")
    config.save_calibrated_adjudicator(tmp_path, {"catalyst": 10, "bogus_cap": 99})
    caps = config.load_adjudicator(tmp_path)
    assert caps["catalyst"] == 10
    assert "bogus_cap" not in caps
