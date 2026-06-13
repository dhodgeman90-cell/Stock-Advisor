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
            "analyst": 8, "insider_buy": 12, "insider_sell": 10, "earnings_soon": 6}
THRESH = {"social_min_mentions": 25, "earnings_window_days": 5}


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


def test_veto_wins_over_congress_buy():
    risk = {"risk_level": "high", "red_flags": ["fraud"], "veto": True, "reason": "probe"}
    out = adjudicator.adjudicate(
        {"ticker": "X", "score": 70}, NEUTRAL_NEWS, risk, NEUTRAL_CTX, EXT_CAPS,
        thresholds=THRESH, congress={"net_side": "buy", "n_members": 3},
    )
    assert out["vetoed"] is True
    assert out["final_score"] == 70
