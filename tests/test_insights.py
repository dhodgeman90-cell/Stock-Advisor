import datetime as dt

from src import insights


# --- analyst ratings / price targets --------------------------------------
def test_parse_analyst_computes_upside():
    info = {"recommendationKey": "buy", "recommendationMean": 2.1,
            "targetMeanPrice": 120.0, "numberOfAnalystOpinions": 15}
    out = insights._parse_analyst(info, current_price=100.0)
    assert out["rating"] == "buy"
    assert out["target"] == 120.0
    assert out["upside_pct"] == 20.0
    assert out["n_analysts"] == 15


def test_parse_analyst_missing_target_is_none():
    out = insights._parse_analyst({"recommendationKey": "hold"}, current_price=50.0)
    assert out["rating"] == "hold"
    assert out["upside_pct"] is None


def test_get_analyst_signal_uses_injected_fetch():
    out = insights.get_analyst_signal(
        "AAPL",
        fetch=lambda t: ({"recommendationKey": "strong_buy", "targetMeanPrice": 200.0,
                          "numberOfAnalystOpinions": 30}, 160.0),
    )
    assert out["rating"] == "strong_buy"
    assert round(out["upside_pct"], 1) == 25.0


def test_get_analyst_signal_falls_back_on_error():
    def boom(t):
        raise RuntimeError("yf down")
    out = insights.get_analyst_signal("AAPL", fetch=boom)
    assert out["rating"] is None and out["upside_pct"] is None


# --- corporate insider (Form 4) buying ------------------------------------
def test_parse_insider_nets_buys_and_sells():
    records = [
        {"Transaction": "Purchase", "Value": 50000},
        {"Transaction": "Purchase", "Value": 20000},
        {"Transaction": "Sale", "Value": 10000},
        {"Transaction": "Stock Gift", "Value": 999},     # ignored (not directional)
    ]
    out = insights._parse_insider(records)
    assert out["n_buys"] == 2
    assert out["n_sells"] == 1
    assert out["buy_value"] == 70000
    assert out["net_side"] == "buy"


def test_parse_insider_empty_is_no_opinion():
    out = insights._parse_insider([])
    assert out["net_side"] is None
    assert out["n_buys"] == 0


# --- earnings gap guard ----------------------------------------------------
def test_parse_earnings_days_until():
    cal = {"Earnings Date": [dt.date(2026, 6, 16)]}
    out = insights._parse_earnings(cal, today=dt.date(2026, 6, 13))
    assert out["days_until"] == 3
    assert out["next_earnings"] == "2026-06-16"


def test_parse_earnings_picks_soonest_future_date():
    cal = {"Earnings Date": [dt.date(2026, 1, 1), dt.date(2026, 6, 20)]}
    out = insights._parse_earnings(cal, today=dt.date(2026, 6, 13))
    assert out["next_earnings"] == "2026-06-20"
    assert out["days_until"] == 7


def test_parse_earnings_none_when_no_date():
    out = insights._parse_earnings({}, today=dt.date(2026, 6, 13))
    assert out["days_until"] is None


# --- short interest / squeeze ---------------------------------------------
def test_parse_short_converts_float_pct_and_rising():
    info = {"shortPercentOfFloat": 0.1439, "shortRatio": 6.22,
            "sharesShort": 59_000_000, "sharesShortPriorMonth": 50_000_000}
    out = insights._parse_short(info)
    assert out["pct_float"] == 14.39
    assert out["days_to_cover"] == 6.22
    assert out["rising"] is True


def test_parse_short_falling_short_interest():
    info = {"shortPercentOfFloat": 0.05, "sharesShort": 40, "sharesShortPriorMonth": 60}
    out = insights._parse_short(info)
    assert out["rising"] is False


def test_parse_short_missing_fields_are_none():
    out = insights._parse_short({})
    assert out["pct_float"] is None and out["rising"] is None


def test_get_short_signal_uses_injected_fetch():
    out = insights.get_short_signal(
        "GME", fetch=lambda t: ({"shortPercentOfFloat": 0.2, "shortRatio": 5.0,
                                 "sharesShort": 10, "sharesShortPriorMonth": 5}, 30.0))
    assert out["pct_float"] == 20.0 and out["rising"] is True


def test_get_short_signal_falls_back_on_error():
    def boom(t):
        raise RuntimeError("yf down")
    out = insights.get_short_signal("GME", fetch=boom)
    assert out == insights.NEUTRAL_SHORT


# --- analyst estimate-revision momentum -----------------------------------
def test_parse_revisions_up_trend():
    recs = [
        {"GradeDate": dt.date(2026, 6, 10), "Action": "up", "priceTargetAction": "Raises"},
        {"GradeDate": dt.date(2026, 6, 5), "Action": "main", "priceTargetAction": "Raises"},
        {"GradeDate": dt.date(2026, 6, 1), "Action": "down", "priceTargetAction": "Lowers"},
    ]
    out = insights._parse_revisions(recs, today=dt.date(2026, 6, 17))
    assert out["n_up"] == 2 and out["n_down"] == 1
    assert out["revision_trend"] == "up"


def test_parse_revisions_down_trend():
    recs = [
        {"GradeDate": dt.date(2026, 6, 10), "Action": "down", "priceTargetAction": "Lowers"},
        {"GradeDate": dt.date(2026, 6, 9), "Action": "main", "priceTargetAction": "Lowers"},
    ]
    out = insights._parse_revisions(recs, today=dt.date(2026, 6, 17))
    assert out["revision_trend"] == "down"


def test_parse_revisions_window_excludes_old():
    recs = [
        {"GradeDate": dt.date(2026, 1, 1), "Action": "up", "priceTargetAction": "Raises"},
        {"GradeDate": dt.date(2026, 1, 2), "Action": "up", "priceTargetAction": "Raises"},
    ]
    out = insights._parse_revisions(recs, today=dt.date(2026, 6, 17), window_days=90)
    assert out["revision_trend"] == "flat" and out["n_up"] == 0


def test_parse_revisions_single_action_is_flat():
    recs = [{"GradeDate": dt.date(2026, 6, 10), "Action": "up", "priceTargetAction": "Raises"}]
    out = insights._parse_revisions(recs, today=dt.date(2026, 6, 17))
    assert out["revision_trend"] == "flat"        # needs >=2 to call a trend


def test_get_revision_signal_falls_back_on_error():
    def boom(t):
        raise RuntimeError("yf down")
    out = insights.get_revision_signal("AAPL", fetch=boom)
    assert out == insights.NEUTRAL_REVISION
