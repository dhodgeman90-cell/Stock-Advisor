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


def test_missing_adjustment_detail_does_not_raise():
    # the render tests pass adjudicator dicts without structured detail.
    v = verdict.classify({"final_score": 88, "vetoed": False}, buy_threshold=65)
    assert v["call"] == "Buy" and v["reason"]


# ===================== adds_paused must reach the verdict label =====================
# Measured 2026-09-09: 332 "Buy:" verdicts shipped across every briefing while
# config/watchlist.yaml carried adds_paused: true. The flag only zeroed the ROTATION adds
# (main.py:572); the Top Candidates section kept printing "Buy" for eight names a morning.
# With real money live that is the single most misleading thing the app does.

def test_adds_paused_downgrades_buy_to_candidate():
    r = _r(85, [{"key": "catalyst", "points": 15}])
    assert verdict.classify(r, buy_threshold=65)["call"] == "Buy"
    assert verdict.classify(r, buy_threshold=65, adds_paused=True)["call"] == "Candidate"


def test_adds_paused_keeps_the_driver_reason():
    r = _r(85, [{"key": "congress_buy", "points": 18}])
    v = verdict.classify(r, buy_threshold=65, adds_paused=True)
    assert "congressional buying" in v["reason"]


def test_adds_paused_does_not_touch_watch_avoid_or_veto():
    assert verdict.classify(_r(58), buy_threshold=65, adds_paused=True)["call"] == "Watch"
    assert verdict.classify(_r(40), buy_threshold=65, adds_paused=True)["call"] == "Avoid"
    v = verdict.classify(_r(90, vetoed=True, veto_reason="fraud probe"),
                         buy_threshold=65, adds_paused=True)
    assert v["call"] == "Avoid"


def test_adds_paused_still_downgrades_contradictions_to_watch():
    # a contradiction is a stronger statement than "buys are paused" — Watch must win.
    v = verdict.classify(
        _r(100, [{"key": "congress_buy", "points": 18}, {"key": "analyst_bear", "points": -8}]),
        buy_threshold=65, adds_paused=True)
    assert v["call"] == "Watch" and v["contradiction"] is True


# ===================== confidence must be a MEASURED rate, never an ordinal =====================
# Measured 2026-09-09: 368 of 368 confidence tags ever printed were "low confidence".
# "medium"/"high" never printed once, because _confidence short-circuited to "low" whenever
# `underperforming` was True or None and the system has underperformed continuously. The field
# was a constant carrying zero information. It is replaced by the realised beat-SPY rate.

def test_confidence_text_reports_the_measured_rate_and_sample_size():
    txt = verdict.confidence_text({"enough": True, "beat_spy_rate": 45.0, "n_matured": 480})
    assert "45%" in txt and "480" in txt


def test_confidence_text_says_so_when_there_is_no_measured_basis():
    for summary in (None, {}, {"enough": False, "beat_spy_rate": 80.0, "n_matured": 4}):
        txt = verdict.confidence_text(summary)
        assert "no measured" in txt.lower()
        # it must never imply a rate it cannot support
        assert "80%" not in txt


def test_confidence_text_handles_a_missing_rate_without_inventing_one():
    txt = verdict.confidence_text({"enough": True, "beat_spy_rate": None, "n_matured": 480})
    assert "no measured" in txt.lower()


def test_no_bare_ordinal_confidence_tag_survives():
    # the old field is gone; nothing may hand the reader a naked "low/medium/high confidence".
    v = verdict.classify(_r(85, [{"key": "catalyst", "points": 15}]), buy_threshold=65)
    assert v.get("confidence") not in ("low", "medium", "high")
