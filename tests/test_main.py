import datetime as dt

from src import main, config


def _ct(ticker, side, low, high, disclosure):
    return {"ticker": ticker, "member": "Hon. X", "chamber": "house", "party": None,
            "side": side, "amount_low": low, "amount_high": high,
            "transaction_date": disclosure, "disclosure_date": disclosure}


def test_should_skip_today_skips_weekends():
    assert main._should_skip_today(dt.date(2026, 6, 13)) is True    # Saturday
    assert main._should_skip_today(dt.date(2026, 6, 14)) is True    # Sunday
    for d in range(8, 13):                                          # Mon-Fri (no holiday)
        assert main._should_skip_today(dt.date(2026, 6, d)) is False


def test_should_skip_today_skips_market_holidays():
    assert main._should_skip_today(dt.date(2026, 11, 26)) is True   # Thanksgiving
    assert main._should_skip_today(dt.date(2026, 12, 25)) is True   # Christmas


def test_should_skip_today_runs_on_half_days():
    # Day after Thanksgiving: early close, but the market is open and has data.
    assert main._should_skip_today(dt.date(2026, 11, 27)) is False


def test_should_skip_today_force_overrides_everything():
    assert main._should_skip_today(dt.date(2026, 6, 13), force=True) is False    # weekend
    assert main._should_skip_today(dt.date(2026, 12, 25), force=True) is False   # holiday


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


import tests.helpers as helpers
from src.profile import Profile, EnvSecrets


def _seed_min_config(cfg):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "watchlist.yaml").write_text(
        "tickers:\n  - AAA\nsettings:\n  lookback_days: 120\n  shortlist_size: 2\n",
        encoding="utf-8")
    (cfg / "weights.yaml").write_text(
        "weights:\n  breakout: 30\n  volume: 30\n  momentum: 20\n  trend: 15\n  pullback: 5\n",
        encoding="utf-8")
    (cfg / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  news_neg: 10\n  risk_high: 20\n  social: 8\n",
        encoding="utf-8")
    (cfg / "exits.yaml").write_text(
        "defaults:\n  stop_loss_pct: 8\n  take_profit_pct: 20\n"
        "  trend_break_fast: 20\n  trend_break_slow: 50\n"
        "  momentum_fade:\n    rsi_was_above: 70\n    volume_dry_ratio: 0.7\n"
        "backtest:\n  buy_threshold: 65\n  max_hold_days: 60\n"
        "  window_years: 2\n  baseline: equal_weight_watchlist\n",
        encoding="utf-8")
    (cfg / "positions.yaml").write_text("positions: []\n", encoding="utf-8")


def test_run_honors_profile_dirs_and_returns_result(tmp_path, monkeypatch):
    from src import main
    _seed_min_config(tmp_path / "config")

    # Offline: no secrets -> has_llm False -> no Anthropic calls. Stub the network
    # feeds (all of which return empties on failure in production anyway).
    monkeypatch.setattr(main.social, "get_wsb_sentiment", lambda: {})
    monkeypatch.setattr(main.congress, "get_congress_trades", lambda: [])
    monkeypatch.setattr(main.congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    monkeypatch.setattr(main.news, "get_headlines", lambda t: [])

    prices = [10 + i * 0.1 for i in range(160)]   # clean rising series
    fake_fetch = lambda ticker, lookback: helpers.make_df(prices)

    profile = Profile(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        secrets=EnvSecrets(values={}),            # no secrets at all
    )

    result = main.run(profile=profile, force=True, fetch=fake_fetch)

    assert result.skipped is False
    assert result.date  # iso date string
    report = tmp_path / "reports" / f"{result.date}.md"
    assert report.exists()                         # written into the PROFILE dir
    assert result.report_path == report
    assert result.html != ""                       # structured html captured
    assert isinstance(result.ranked, list)
