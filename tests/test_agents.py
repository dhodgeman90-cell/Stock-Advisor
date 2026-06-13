from src import agents
from tests.fakes import FakeClient, BoomClient


def test_extract_json_from_fenced_text():
    text = "Here you go:\n```json\n{\"a\": 1}\n```"
    assert agents.extract_json(text) == {"a": 1}


def test_news_agent_parses_catalyst():
    reply = ('{"catalyst": true, "catalyst_type": "earnings", '
             '"sentiment": "pos", "summary": "Beat estimates."}')
    out = agents.news_agent(FakeClient(reply), "AAPL", ["Apple beats earnings"])
    assert out["catalyst"] is True
    assert out["sentiment"] == "pos"


def test_news_agent_no_headlines_is_neutral():
    out = agents.news_agent(FakeClient("{}"), "AAPL", [])
    assert out["catalyst"] is False
    assert out["sentiment"] == "neutral"


def test_news_agent_falls_back_on_error():
    out = agents.news_agent(BoomClient(), "AAPL", ["something"])
    assert out["catalyst"] is False
    assert out["sentiment"] == "neutral"


def test_risk_agent_parses_veto():
    reply = ('{"risk_level": "high", "red_flags": ["fraud probe"], '
             '"veto": true, "reason": "Active SEC fraud investigation."}')
    out = agents.risk_agent(FakeClient(reply), "XYZ", [10.0, 11.0], ["probe opened"])
    assert out["veto"] is True
    assert out["risk_level"] == "high"


def test_risk_agent_falls_back_to_no_opinion_on_error():
    out = agents.risk_agent(BoomClient(), "XYZ", [10.0, 11.0], [])
    assert out["veto"] is False
    assert out["risk_level"] == "low"   # neutral = no demote, no veto


def test_risk_agent_falls_back_on_junk_reply():
    out = agents.risk_agent(FakeClient("not json at all"), "XYZ", [10.0], [])
    assert out["veto"] is False


def test_context_agent_parses_regime():
    out = agents.context_agent(
        FakeClient('{"regime": "risk_off", "note": "Rates rising."}'),
        "market is jittery",
    )
    assert out["regime"] == "risk_off"


def test_context_agent_falls_back_on_error():
    out = agents.context_agent(BoomClient(), "anything")
    assert out["regime"] == "neutral"


def test_social_agent_parses_credibility():
    reply = ('{"credibility": "high", "contrarian": false, '
             '"summary": "Detailed DD thread with real numbers."}')
    out = agents.social_agent(FakeClient(reply), "GME", ["GME DD: undervalued"])
    assert out["credibility"] == "high"
    assert out["contrarian"] is False


def test_social_agent_flags_contrarian_hype():
    reply = ('{"credibility": "low", "contrarian": true, '
             '"summary": "Pure rocket-emoji hype, no substance."}')
    out = agents.social_agent(FakeClient(reply), "AMC", ["AMC TO THE MOON 🚀🚀"])
    assert out["credibility"] == "low"
    assert out["contrarian"] is True


def test_social_agent_no_posts_is_neutral():
    out = agents.social_agent(FakeClient("{}"), "AAPL", [])
    assert out["credibility"] is None
    assert out["contrarian"] is False


def test_social_agent_falls_back_on_error():
    out = agents.social_agent(BoomClient(), "AAPL", ["something"])
    assert out["credibility"] is None
    assert out["contrarian"] is False
