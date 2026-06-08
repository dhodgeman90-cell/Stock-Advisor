from src import briefing
from tests.fakes import FakeSMTP


def _adjudicated(ticker, final, base, summary, risk_level, reason, adjustments):
    return {
        "ticker": ticker, "base_score": base, "final_score": final,
        "vetoed": False, "veto_reason": "",
        "news": {"summary": summary},
        "risk": {"risk_level": risk_level, "reason": reason},
        "regime": "risk_on", "adjustments": adjustments,
    }


def test_render_briefing_orders_and_shows_sections():
    ranked = [
        _adjudicated("HI", 88, 80, "new deal", "low", "no flags", ["+15 catalyst"]),
        _adjudicated("LO", 60, 65, "no catalyst", "medium", "earnings soon", ["-8 medium risk"]),
    ]
    vetoed = [{"ticker": "BAD", "veto_reason": "fraud probe"}]
    others = [{"ticker": "MEH", "score": 40}]
    excluded = [{"ticker": "PENNY", "reason": "price below floor"}]

    text = briefing.render_briefing(ranked, vetoed, others, excluded,
                                    "2026-06-08", "risk_on", "Market upbeat.")

    assert "2026-06-08" in text
    assert text.index("HI") < text.index("LO")     # ranked order preserved
    assert "fraud probe" in text                    # veto shown
    assert "MEH" in text                            # others shown
    assert "PENNY" in text                          # excluded shown
    assert "not financial advice" in text.lower()


def test_send_email_logs_in_and_sends():
    fake = FakeSMTP()
    briefing.send_email(
        "Subject Line", "Body text",
        host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        smtp_factory=lambda: fake,
    )
    assert fake.logged_in == ("me@test.com", "pw")
    assert fake.sent_message["Subject"] == "Subject Line"
    assert fake.sent_message["To"] == "you@test.com"


def _holding(ticker, price, pct, signals, risk_flag=None):
    h = {"ticker": ticker, "current_price": price, "pct_from_entry": pct, "signals": signals}
    if risk_flag:
        h["risk_flag"] = risk_flag
    return h


def test_render_holdings_section_empty():
    text = briefing.render_holdings_section([])
    assert "No tracked positions" in text


def test_render_holdings_section_shows_signals_and_clean_lines():
    holdings = [
        _holding("NVDA", 109.0, -9.2,
                 [{"type": "stop_loss", "level": "sell", "emoji": "🔴",
                   "detail": "down 9.2% from entry (stop -8%)"}]),
        _holding("AAPL", 150.0, 5.0, []),   # clean
    ]
    text = briefing.render_holdings_section(holdings)
    assert "NVDA" in text
    assert "stop loss" in text                 # underscores rendered as spaces
    assert "down 9.2%" in text
    assert "no exit signal" in text            # clean holding line for AAPL


def test_render_briefing_puts_holdings_above_candidates():
    ranked = [_adjudicated("HI", 88, 80, "new deal", "low", "no flags", ["+15 catalyst"])]
    holdings = [_holding("NVDA", 109.0, -9.2,
                         [{"type": "stop_loss", "level": "sell", "emoji": "🔴",
                           "detail": "down 9.2%"}])]
    text = briefing.render_briefing(ranked, [], [], [], "2026-06-08",
                                    "risk_on", "Upbeat.", holdings=holdings)
    assert text.index("NVDA") < text.index("Top candidates")
