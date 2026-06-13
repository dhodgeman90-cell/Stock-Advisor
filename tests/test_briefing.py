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


def test_send_email_sends_multipart_when_html_given():
    fake = FakeSMTP()
    briefing.send_email(
        "Subj", "plain body", host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        html_body="<p>hi</p>", smtp_factory=lambda: fake,
    )
    msg = fake.sent_message
    assert msg.is_multipart()
    types = [p.get_content_type() for p in msg.iter_parts()]
    assert "text/plain" in types
    assert "text/html" in types


def test_send_email_plain_only_when_no_html():
    fake = FakeSMTP()
    briefing.send_email(
        "Subj", "plain body", host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        smtp_factory=lambda: fake,
    )
    assert not fake.sent_message.is_multipart()
    assert fake.sent_message.get_content_type() == "text/plain"


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


def test_render_holdings_section_shows_risk_flag():
    holdings = [_holding("NVDA", 109.0, -3.0, [], risk_flag="earnings tomorrow")]
    text = briefing.render_holdings_section(holdings)
    assert "⚠️" in text
    assert "earnings tomorrow" in text


def test_render_holdings_section_handles_unavailable_price():
    holdings = [_holding("NVDA", float("nan"), 0.0, [], risk_flag="no valid price data")]
    text = briefing.render_holdings_section(holdings)
    assert "price unavailable" in text
    assert "nan" not in text.lower()


def test_render_briefing_puts_holdings_above_candidates():
    ranked = [_adjudicated("HI", 88, 80, "new deal", "low", "no flags", ["+15 catalyst"])]
    holdings = [_holding("NVDA", 109.0, -9.2,
                         [{"type": "stop_loss", "level": "sell", "emoji": "🔴",
                           "detail": "down 9.2%"}])]
    text = briefing.render_briefing(ranked, [], [], [], "2026-06-08",
                                    "risk_on", "Upbeat.", holdings=holdings)
    assert text.index("NVDA") < text.index("Top candidates")


def test_signal_pill_colors_by_level():
    assert briefing._signal_pill("sell")  == ("#fee2e2", "#991b1b")   # red
    assert briefing._signal_pill("trim")  == ("#fef9c3", "#854d0e")   # amber
    assert briefing._signal_pill("watch") == ("#fef9c3", "#854d0e")   # amber
    assert briefing._signal_pill("hold")  == ("#dcfce7", "#166534")   # green


def test_signal_pill_unknown_level_defaults_to_green():
    assert briefing._signal_pill("whatever") == ("#dcfce7", "#166534")


def test_render_briefing_html_has_header_table_and_pills():
    ranked = [_adjudicated("MSFT", 78, 74, "cloud demand strong", "low", "no flags", ["+4 news"])]
    holdings = [
        _holding("NVDA", 128.40, 6.6, []),                              # clean -> green hold
        _holding("AAPL", 182.10, -3.2,
                 [{"type": "momentum_fade", "level": "watch", "emoji": "🟡",
                   "detail": "rsi cooling"}]),
    ]
    html_out = briefing.render_briefing_html(
        ranked, [], [], [], "2026-06-08", "risk_on", "Broad uptrend.", holdings=holdings)
    assert "Stock Advisor" in html_out
    assert "2026-06-08" in html_out
    assert "<table" in html_out                       # holdings table
    assert "#dcfce7" in html_out                       # green hold pill (NVDA, no signals)
    assert "#fef9c3" in html_out                       # amber watch pill (AAPL)
    assert "MSFT" in html_out                          # candidate card


def test_render_briefing_html_escapes_untrusted_text():
    ranked = [_adjudicated("X", 70, 70, "deal <b>&</b> close", "low", "fine", [])]
    html_out = briefing.render_briefing_html(
        ranked, [], [], [], "2026-06-08", "risk_on", "ok", holdings=[])
    assert "deal <b>&</b>" not in html_out             # raw HTML must not pass through
    assert "&lt;b&gt;" in html_out                      # it is escaped instead


def test_render_briefing_html_handles_unavailable_price():
    holdings = [_holding("NVDA", float("nan"), 0.0, [])]
    html_out = briefing.render_briefing_html(
        [], [], [], [], "2026-06-08", "risk_on", "ok", holdings=holdings)
    assert "price unavailable" in html_out
    assert "$nan" not in html_out.lower()      # NaN price not formatted as a number


def test_render_rotation_section_lists_each_action():
    plan = {
        "exits": [{"ticker": "AAPL", "reason": "down 13% from peak"}],
        "trims": [{"ticker": "NVDA", "reason": "congress selling"}],
        "adds": [{"ticker": "SMCI", "final_score": 80, "conviction": "high",
                  "reason": "high-conviction setup"}],
        "hold": [{"ticker": "T"}],
    }
    text = briefing.render_rotation_section(plan)
    assert "rotation" in text.lower()
    assert "AAPL" in text and "down 13%" in text       # exit
    assert "NVDA" in text and "congress selling" in text  # trim
    assert "SMCI" in text                               # add
    assert "T" in text                                  # hold


def test_render_rotation_section_empty_is_hold_steady():
    text = briefing.render_rotation_section({"exits": [], "trims": [], "adds": [], "hold": []})
    assert "hold steady" in text.lower()


def test_candidate_insight_lines_show_badges_when_present():
    r = {
        "congress": {"net_side": "buy", "n_members": 2, "most_recent_disclosure": "2026-06-10"},
        "insider": {"net_side": "buy", "n_buys": 3, "n_sells": 0},
        "analyst": {"rating": "buy", "upside_pct": 15.0},
        "earnings": {"days_until": 3, "next_earnings": "2026-06-16"},
        "social": "+8.5 WSB buzz (trust 85%)",
    }
    lines = briefing._candidate_insight_lines(r)
    joined = "\n".join(lines)
    assert "🏛️" in joined and "buy" in joined            # congress
    assert "👔" in joined                                 # insider
    assert "🎯" in joined and "15" in joined              # analyst upside
    assert "📅" in joined and "3" in joined               # earnings countdown
    assert "💬" in joined and "WSB" in joined             # social


def test_candidate_insight_lines_empty_when_no_signals():
    assert briefing._candidate_insight_lines({}) == []


def test_render_discovery_section_lists_movers():
    congress_movers = [{"ticker": "BIG", "member": "Hon. Jane Doe", "side": "buy",
                        "amount_low": 100001, "amount_high": 250000,
                        "disclosure_date": "2026-06-10"}]
    wsb_movers = [{"ticker": "ZYX", "mentions": 500, "mentions_change": 400}]
    text = briefing.render_discovery_section(congress_movers, wsb_movers)
    assert "Outside the watchlist" in text
    assert "BIG" in text and "Jane Doe" in text
    assert "ZYX" in text and "400" in text


def test_render_discovery_section_empty_returns_blank():
    assert briefing.render_discovery_section([], []) == ""


def test_render_briefing_includes_rotation_and_discovery():
    ranked = [_adjudicated("HI", 88, 80, "deal", "low", "fine", [])]
    plan = {"exits": [], "trims": [], "adds": [{"ticker": "SMCI", "final_score": 80,
            "conviction": "high", "reason": "setup"}], "hold": []}
    discovery = {"congress": [{"ticker": "BIG", "member": "Hon. X", "side": "buy",
                 "amount_low": 100001, "amount_high": 250000, "disclosure_date": "2026-06-10"}],
                 "wsb": [{"ticker": "ZYX", "mentions": 500, "mentions_change": 400}]}
    text = briefing.render_briefing(ranked, [], [], [], "2026-06-08", "risk_on", "ok",
                                    holdings=[], rotation_plan=plan, discovery=discovery)
    assert "SMCI" in text                              # rotation add surfaced
    assert "BIG" in text                               # discovery surfaced
    assert text.index("rotation") < text.index("Top candidates") if "rotation" in text.lower() else True


def test_render_briefing_html_includes_rotation_and_discovery():
    ranked = [_adjudicated("HI", 88, 80, "deal", "low", "fine", [])]
    plan = {"exits": [{"ticker": "AAPL", "reason": "stop hit"}], "trims": [], "adds": [], "hold": []}
    discovery = {"congress": [{"ticker": "BIG", "member": "Hon. X", "side": "buy",
                 "amount_low": 100001, "amount_high": 250000, "disclosure_date": "2026-06-10"}],
                 "wsb": []}
    html_out = briefing.render_briefing_html(ranked, [], [], [], "2026-06-08", "risk_on", "ok",
                                             holdings=[], rotation_plan=plan, discovery=discovery)
    assert "AAPL" in html_out                          # rotation exit
    assert "BIG" in html_out                           # discovery
    assert "Outside the watchlist" in html_out


def test_render_briefing_html_omits_empty_sections_and_shows_vetoed():
    vetoed = [{"ticker": "GME", "veto_reason": "headline spike"}]
    html_out = briefing.render_briefing_html(
        [], vetoed, [], [], "2026-06-08", "risk_on", "ok", holdings=[])
    assert "Vetoed" in html_out
    assert "headline spike" in html_out
    assert "Other scored" not in html_out              # empty others omitted
    assert "Excluded" not in html_out                  # empty excluded omitted
    assert "No tracked positions" in html_out          # empty holdings note
