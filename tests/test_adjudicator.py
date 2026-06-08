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
