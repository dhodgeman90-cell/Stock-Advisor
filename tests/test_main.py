import datetime as dt

from src import main, config


def _ct(ticker, side, low, high, disclosure):
    return {"ticker": ticker, "member": "Hon. X", "chamber": "house", "party": None,
            "side": side, "amount_low": low, "amount_high": high,
            "transaction_date": disclosure, "disclosure_date": disclosure}


def test_should_skip_weekend_skips_saturday_and_sunday_only():
    assert main._should_skip_weekend(dt.date(2026, 6, 13)) is True   # Saturday
    assert main._should_skip_weekend(dt.date(2026, 6, 14)) is True   # Sunday
    for d in range(8, 13):                                           # Mon-Fri
        assert main._should_skip_weekend(dt.date(2026, 6, d)) is False


def test_should_skip_weekend_force_overrides_the_weekend():
    assert main._should_skip_weekend(dt.date(2026, 6, 13), force=True) is False
    assert main._should_skip_weekend(dt.date(2026, 6, 14), force=True) is False


def test_discovery_feed_excludes_known_tickers_and_small_or_quiet_names():
    today = dt.date(2026, 6, 12)
    congress_trades = [
        _ct("BIG", "buy", 100001, 250000, "2026-06-10"),    # large, recent, untracked -> in
        _ct("AAPL", "buy", 100001, 250000, "2026-06-10"),   # large but already held -> out
        _ct("SMALL", "buy", 1001, 15000, "2026-06-10"),     # too small -> out
    ]
    wsb_map = {
        "ZYX": {"mentions": 500, "mentions_change": 400},   # surging, untracked -> in
        "AAPL": {"mentions": 600, "mentions_change": 500},  # surging but held -> out
        "QUIET": {"mentions": 5, "mentions_change": 3},      # below min mentions -> out
    }
    feed = main._discovery_feed(
        congress_trades, wsb_map, known_tickers={"AAPL"},
        signals_cfg=config.SIGNAL_DEFAULTS, today=today,
    )
    assert [t["ticker"] for t in feed["congress"]] == ["BIG"]
    assert [w["ticker"] for w in feed["wsb"]] == ["ZYX"]
