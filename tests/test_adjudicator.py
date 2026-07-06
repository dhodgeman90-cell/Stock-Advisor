from src import adjudicator

CAPS = {"catalyst": 15, "news_negative": 10, "risk_high": 20, "risk_medium": 8, "regime": 5}
NEUTRAL_NEWS = {"catalyst": False, "catalyst_type": "", "sentiment": "neutral", "summary": ""}
NEUTRAL_RISK = {"risk_level": "low", "red_flags": [], "veto": False, "reason": ""}
NEUTRAL_CTX = {"regime": "neutral", "note": ""}


def test_veto_excludes_and_keeps_base():
    risk = {"risk_level": "high", "red_flags": ["fraud"], "veto": True, "reason": "fraud probe"}
    out = adjudicator.adjudicate({"ticker": "X", "score": 80}, NEUTRAL_NEWS, risk, NEUTRAL_CTX, CAPS)
    assert out["vetoed"] is True
    assert out["final_score"] == 80
    assert out["veto_reason"] == "fraud probe"


def test_high_risk_and_catalyst_net_adjustment():
    news = {"catalyst": True, "catalyst_type": "deal", "sentiment": "pos", "summary": ""}
    risk = {"risk_level": "high", "red_flags": [], "veto": False, "reason": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 80}, news, risk, NEUTRAL_CTX, CAPS)
    assert out["vetoed"] is False
    assert out["final_score"] == 75   # 80 - 20 (high risk) + 15 (catalyst)


def test_clamps_to_100():
    news = {"catalyst": True, "catalyst_type": "", "sentiment": "pos", "summary": ""}
    ctx = {"regime": "risk_on", "note": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 95}, news, NEUTRAL_RISK, ctx, CAPS)
    assert out["final_score"] == 100   # 95 + 15 + 5 -> clamped


def test_negative_news_and_risk_off():
    news = {"catalyst": False, "catalyst_type": "", "sentiment": "neg", "summary": ""}
    ctx = {"regime": "risk_off", "note": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 50}, news, NEUTRAL_RISK, ctx, CAPS)
    assert out["final_score"] == 35   # 50 - 10 (neg news) - 5 (risk-off)


# ---- new signal sources (congress, insider, analyst, earnings, social) ----
EXT_CAPS = {**CAPS, "congress_buy": 18, "congress_sell": 18, "social": 10,
            "analyst": 8, "insider_buy": 12, "insider_sell": 10, "earnings_soon": 6,
            "edgar_catalyst": 15, "activist_stake": 12, "options_flow": 8,
            "short_squeeze": 10, "estimate_revision": 5}
THRESH = {"social_min_mentions": 25, "earnings_window_days": 5,
          "options_min_volume": 1000, "options_unusual_ratio": 0.5, "short_high_pct": 20}


def _adj(score, **kw):
    return adjudicator.adjudicate(
        {"ticker": "X", "score": score}, NEUTRAL_NEWS, NEUTRAL_RISK, NEUTRAL_CTX,
        EXT_CAPS, thresholds=THRESH, **kw,
    )


def test_congress_buy_boosts_heavily():
    out = _adj(60, congress={"net_side": "buy", "n_members": 2, "most_recent_disclosure": "2026-06-10"})
    assert out["final_score"] == 78        # 60 + 18


def test_congress_sell_demotes():
    out = _adj(60, congress={"net_side": "sell", "n_members": 1, "most_recent_disclosure": "2026-06-10"})
    assert out["final_score"] == 42        # 60 - 18


def test_insider_buy_boosts():
    out = _adj(60, insider={"net_side": "buy", "n_buys": 3, "n_sells": 0})
    assert out["final_score"] == 72        # 60 + 12


def test_analyst_bullish_and_bearish():
    assert _adj(60, analyst={"rating": "buy", "upside_pct": 15})["final_score"] == 68
    assert _adj(60, analyst={"rating": "sell", "upside_pct": -10})["final_score"] == 52


def test_earnings_within_window_demotes_new_entry():
    out = _adj(60, earnings={"days_until": 2, "next_earnings": "2026-06-15"})
    assert out["final_score"] == 54        # 60 - 6


def test_trusted_bullish_social_adds_scaled_points():
    wsb = {"mentions": 100, "mentions_change": 50, "rank_change": 2}
    out = _adj(60, wsb=wsb, social_view={"credibility": "high", "contrarian": False})
    # trust = 0.4 + 0.2(base>=60) + 0.25(high cred) = 0.85; applied = 10 * 0.85
    assert out["social_trust"] == 0.85
    assert out["final_score"] == 68.5


def test_contrarian_social_subtracts():
    wsb = {"mentions": 100, "mentions_change": 60, "rank_change": 1}
    out = _adj(65, wsb=wsb, social_view={"credibility": "med", "contrarian": True})
    # trust = 0.4 + 0.2 + 0.10 = 0.70; applied 7; contrarian -> subtract
    assert out["final_score"] == 58.0


def test_social_skipped_below_min_mentions():
    wsb = {"mentions": 10, "mentions_change": 50, "rank_change": 3}
    out = _adj(60, wsb=wsb, social_view={"credibility": "high", "contrarian": False})
    assert out["final_score"] == 60        # not enough buzz to count


# ---- SEC EDGAR / options / short / estimate revisions ----
def test_edgar_catalyst_boosts():
    out = _adj(60, edgar={"catalyst": True, "catalyst_types": ["reported earnings"],
                          "severe": False, "negative": False, "activist": False})
    assert out["final_score"] == 75       # 60 + 15


def test_edgar_severe_penalizes_like_high_risk():
    out = _adj(60, edgar={"catalyst": False, "severe": True, "severe_reason": "delisting notice",
                          "negative": False, "activist": False})
    assert out["final_score"] == 40       # 60 - 20 (risk_high cap)


def test_edgar_activist_stacks_on_catalyst():
    out = _adj(50, edgar={"catalyst": True, "catalyst_types": ["entered a material agreement"],
                          "severe": False, "negative": False, "activist": True})
    assert out["final_score"] == 77       # 50 + 15 + 12


def test_options_bullish_flow_only_when_unusual_and_liquid():
    bull = {"direction": "bullish", "pc_ratio": 0.2, "call_volume": 2000,
            "put_volume": 100, "vol_oi_ratio": 1.2}
    assert _adj(60, options=bull)["final_score"] == 68        # 60 + 8
    thin = {**bull, "call_volume": 100, "put_volume": 10}      # below min_volume
    assert _adj(60, options=thin)["final_score"] == 60        # ignored


def test_options_bearish_flow_penalizes():
    bear = {"direction": "bearish", "pc_ratio": 2.5, "call_volume": 200,
            "put_volume": 2000, "vol_oi_ratio": 0.9}
    assert _adj(60, options=bear)["final_score"] == 52        # 60 - 8


def test_short_squeeze_bonus_with_strong_chart():
    out = _adj(65, short={"pct_float": 25.0, "days_to_cover": 6.0})
    assert out["final_score"] == 75       # base>=60 -> squeeze setup +10


def test_short_crowded_penalty_on_weak_chart():
    out = _adj(40, short={"pct_float": 25.0, "days_to_cover": 6.0})
    assert out["final_score"] == 30       # weak chart, no buzz -> crowded short -10


def test_short_squeeze_uses_wsb_corroboration():
    out = _adj(40, short={"pct_float": 30.0}, wsb={"mentions": 5, "mentions_change": 80})
    assert out["final_score"] == 50       # weak chart but WSB rising -> squeeze +10


def test_low_short_interest_ignored():
    out = _adj(60, short={"pct_float": 5.0, "days_to_cover": 1.0})
    assert out["final_score"] == 60


def test_estimate_revision_up_and_down():
    assert _adj(60, revision={"revision_trend": "up", "n_up": 3, "n_down": 0})["final_score"] == 65
    assert _adj(60, revision={"revision_trend": "down", "n_up": 0, "n_down": 3})["final_score"] == 55
    assert _adj(60, revision={"revision_trend": "flat", "n_up": 1, "n_down": 1})["final_score"] == 60


def test_veto_wins_over_edgar_catalyst():
    risk = {"risk_level": "high", "red_flags": [], "veto": True, "reason": "fraud"}
    out = adjudicator.adjudicate(
        {"ticker": "X", "score": 70}, NEUTRAL_NEWS, risk, NEUTRAL_CTX, EXT_CAPS,
        thresholds=THRESH, edgar={"catalyst": True, "catalyst_types": ["x"]},
    )
    assert out["vetoed"] is True and out["final_score"] == 70


def test_veto_wins_over_congress_buy():
    risk = {"risk_level": "high", "red_flags": ["fraud"], "veto": True, "reason": "probe"}
    out = adjudicator.adjudicate(
        {"ticker": "X", "score": 70}, NEUTRAL_NEWS, risk, NEUTRAL_CTX, EXT_CAPS,
        thresholds=THRESH, congress={"net_side": "buy", "n_members": 3},
    )
    assert out["vetoed"] is True
    assert out["final_score"] == 70


# ---- structured per-signal attribution (adjustment_detail) ----
def test_adjustment_detail_is_structured_and_reproduces_score():
    out = _adj(60, congress={"net_side": "buy", "n_members": 2},
               analyst={"rating": "sell", "upside_pct": -10})
    detail = {d["key"]: d["points"] for d in out["adjustment_detail"]}
    assert detail["congress_buy"] == 18       # signed points, positive for a buy
    assert detail["analyst_bear"] == -8       # negative for a demotion
    # base + sum(points) reproduces the final score exactly (no clamp here)
    assert 60 + sum(d["points"] for d in out["adjustment_detail"]) == out["final_score"]


def test_veto_has_empty_adjustment_detail():
    risk = {"risk_level": "high", "red_flags": [], "veto": True, "reason": "fraud"}
    out = adjudicator.adjudicate({"ticker": "X", "score": 70}, NEUTRAL_NEWS, risk,
                                 NEUTRAL_CTX, EXT_CAPS, thresholds=THRESH)
    assert out["adjustment_detail"] == []
