from src import verdict


def _r(final, detail=None, vetoed=False, veto_reason=""):
    return {"final_score": final, "adjustment_detail": detail or [],
            "vetoed": vetoed, "veto_reason": veto_reason}


def test_buy_when_at_or_above_threshold():
    v = verdict.classify(_r(70, [{"key": "catalyst", "points": 15}]), buy_threshold=65)
    assert v["call"] == "Buy"


def test_watch_just_below_threshold():
    assert verdict.classify(_r(58), buy_threshold=65)["call"] == "Watch"


def test_avoid_well_below_threshold():
    assert verdict.classify(_r(40), buy_threshold=65)["call"] == "Avoid"


def test_veto_is_always_avoid_with_reason():
    v = verdict.classify(_r(90, vetoed=True, veto_reason="active fraud probe"), buy_threshold=65)
    assert v["call"] == "Avoid"
    assert "fraud probe" in v["reason"]


def test_high_score_with_bearish_analyst_downgrades_to_watch():
    # the "100/100 but analysts bearish" case: score says Buy, evidence disagrees -> Watch.
    v = verdict.classify(
        _r(100, [{"key": "congress_buy", "points": 18}, {"key": "analyst_bear", "points": -8}]),
        buy_threshold=65)
    assert v["call"] == "Watch"
    assert v["contradiction"] is True
    assert "conflict" in v["reason"]


def test_reason_names_the_largest_driver():
    v = verdict.classify(
        _r(80, [{"key": "catalyst", "points": 15}, {"key": "congress_buy", "points": 18}]),
        buy_threshold=65)
    assert "congressional buying" in v["reason"]   # +18 beats +15


def test_reason_uses_held_back_for_negative_driver():
    v = verdict.classify(_r(52, [{"key": "earnings_soon", "points": -6}]), buy_threshold=65)
    assert v["reason"].startswith("held back by")


def test_technicals_only_when_no_signals():
    assert "technicals only" in verdict.classify(_r(70), buy_threshold=65)["reason"]


def test_underperforming_forces_low_confidence():
    clean_buy = _r(85, [{"key": "catalyst", "points": 15}, {"key": "congress_buy", "points": 18}])
    assert verdict.classify(clean_buy, buy_threshold=65)["confidence"] == "high"
    assert verdict.classify(clean_buy, buy_threshold=65,
                            underperforming=True)["confidence"] == "low"


def test_missing_adjustment_detail_does_not_raise():
    # the render tests pass adjudicator dicts without structured detail.
    v = verdict.classify({"final_score": 88, "vetoed": False}, buy_threshold=65)
    assert v["call"] == "Buy" and v["reason"]
