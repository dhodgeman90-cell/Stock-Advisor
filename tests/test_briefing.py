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
