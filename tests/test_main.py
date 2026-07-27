import datetime as dt

import pandas as pd

from src import (main, config, scoring, onboarding, broker, social, congress,
                 market, insights, edgar, options)
from src.profile import Profile


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


def test_count_live_signals_ignores_neutral_bundle():
    # A fully-degraded enrichment bundle counts 0 live signals; one real analyst dict counts 1.
    # This is what lets the briefing flag a momentum-only pick as "thin data".
    assert main._count_live_signals(main._neutral_bundle()) == 0
    sigs = {**main._neutral_bundle(), "analyst": {"rating": "buy", "upside_pct": 10}}
    assert main._count_live_signals(sigs) == 1


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


# Adjudicator caps mirroring config/adjudicator.yaml (for the projection helper tests).
_CAPS = {
    "catalyst": 15, "news_negative": 10, "risk_high": 20, "risk_medium": 8,
    "regime": 5, "congress_buy": 18, "congress_sell": 18, "insider_buy": 12,
    "insider_sell": 10, "analyst": 8, "earnings_soon": 6, "social": 10,
}
_CTX = {"regime": "neutral", "note": ""}
_THR = {"social_min_mentions": 25, "earnings_window_days": 5}


def test_projected_score_lifts_low_base_over_threshold_via_deterministic_boosts():
    # base 59 + congress buy (+18) + analysts bullish (+8): raw 85, but the positive-stack cap
    # compresses the pile past the knee to ~84 — still well over the 65 gate, which is the point
    # (AI-worthiness keys off CROSSING the threshold, not the exact score). Used NO AI.
    score = main._projected_score(
        59, _CTX, _CAPS,
        congress={"net_side": "buy", "n_members": 3},
        analyst={"rating": "strong_buy", "upside_pct": 16},
        thresholds=_THR,
    )
    assert 83 < score < 85
    assert score >= 65        # the AI-worthiness gate it must clear


def test_projected_score_stays_low_without_boosts():
    assert main._projected_score(40, _CTX, _CAPS, thresholds=_THR) == 40


def test_ai_is_actionable_true_when_holding_has_exit_signal():
    holdings = [{"ticker": "SOXL", "signals": [{"type": "stop_loss"}]}]
    assert main._ai_is_actionable(holdings, projected_scores=[], buy_threshold=65) is True


def test_ai_is_actionable_true_when_candidate_projects_as_buy():
    assert main._ai_is_actionable(holdings=[], projected_scores=[70], buy_threshold=65) is True


def test_ai_is_actionable_false_on_a_quiet_day():
    # No flagged holdings and no candidate PROJECTS as a buy -> no Claude tokens spent.
    holdings = [{"ticker": "SOXL", "signals": []}]
    assert main._ai_is_actionable(holdings, projected_scores=[50, 64], buy_threshold=65) is False


import pandas as pd

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


def _stub_signal_feeds(monkeypatch):
    """Neutralize the per-candidate + macro network feeds added for deep sourcing, so the
    older run-tests (which stub the original feeds by hand) stay fully offline."""
    monkeypatch.setattr(main.market, "get_macro_context",
                        lambda *a, **k: dict(main.market.NEUTRAL_MACRO))
    monkeypatch.setattr(main.insights, "get_short_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_revision_signal", lambda t: None)
    monkeypatch.setattr(main.edgar, "load_cik_map", lambda **kw: {})
    monkeypatch.setattr(main.edgar, "get_sec_signal", lambda t, cik_map, **kw: None)
    monkeypatch.setattr(main.options, "get_options_signal", lambda t: None)


def test_run_honors_profile_dirs_and_returns_result(tmp_path, monkeypatch):
    from src import main
    _seed_min_config(tmp_path / "config")

    # Offline: no secrets -> has_llm False -> no Anthropic calls. Stub the network
    # feeds (all of which return empties on failure in production anyway).
    monkeypatch.setattr(main.social, "get_wsb_sentiment", lambda **kw: {})
    monkeypatch.setattr(main.congress, "get_congress_trades", lambda **kw: [])
    monkeypatch.setattr(main.congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    _stub_signal_feeds(monkeypatch)
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


# ---- Phase 4: opt-in RS entry re-rank + defensive regime overlay ----

def test_rs_reranked_orders_by_relative_strength_not_input_order():
    spy_close = pd.Series([100.0] * 60)                          # flat market
    df_by = {"STRONG": helpers.make_df(list(range(100, 160))),   # rises vs flat SPY -> high RS
             "WEAK": helpers.make_df([160.0 - i for i in range(60)])}  # downtrend -> low RS
    ranked = [{"ticker": "WEAK", "rank_score": 99}, {"ticker": "STRONG", "rank_score": 1}]
    out = main._rs_reranked(ranked, df_by, spy_close)
    assert out[0]["ticker"] == "STRONG"                          # RS overrides the input order


def test_confirmed_regime_risk_off_on_crash_risk_on_on_uptrend():
    crash = helpers.make_df([100.0 + i for i in range(250)] + [349.0 - 3.0 * i for i in range(60)])
    assert main._confirmed_regime(crash) == "risk_off"
    assert main._confirmed_regime(helpers.make_df(list(range(100, 400)))) == "risk_on"


def test_confirmed_regime_defaults_risk_on_on_short_history():
    assert main._confirmed_regime(helpers.make_df([100.0] * 20)) == "risk_on"


def test_run_routes_signal_caches_to_profile_data_dir(tmp_path, monkeypatch):
    """main.run must thread profile.data_dir into the WSB + congress cache paths so a
    per-user install never writes signal caches into the repo/install dir (data isolation)."""
    from src import main
    _seed_min_config(tmp_path / "config")

    captured = {}

    def fake_wsb(cache_path=None, **kw):
        captured["wsb"] = cache_path
        return {}

    def fake_congress(cache_path=None, **kw):
        captured["congress"] = cache_path
        return []

    monkeypatch.setattr(main.social, "get_wsb_sentiment", fake_wsb)
    monkeypatch.setattr(main.congress, "get_congress_trades", fake_congress)
    monkeypatch.setattr(main.congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    _stub_signal_feeds(monkeypatch)
    monkeypatch.setattr(main.news, "get_headlines", lambda t: [])

    fake_fetch = lambda ticker, lookback: helpers.make_df([10 + i * 0.1 for i in range(160)])
    profile = Profile(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        secrets=EnvSecrets(values={}),
    )

    main.run(profile=profile, force=True, fetch=fake_fetch)

    assert captured["wsb"] == profile.data_dir / "wsb_sentiment.json"
    assert captured["congress"] == profile.data_dir / "congress_trades.json"


def test_run_spends_ai_on_deterministically_boosted_buy_candidate(tmp_path, monkeypatch):
    """The bug: AI news/risk were gated on the raw BASE score, so a candidate that becomes
    a buy via deterministic boosts (congress) was skipped and showed 'news agent unavailable'.
    After the fix, AI runs for any candidate whose deterministic PROJECTION clears the bar."""
    from src import main
    from src import llm as llm_mod
    _seed_min_config(tmp_path / "config")
    # full caps so the congress-buy boost can apply in the projection + adjudication
    (tmp_path / "config" / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  news_negative: 10\n  risk_high: 20\n  risk_medium: 8\n"
        "  regime: 5\n  congress_buy: 18\n  congress_sell: 18\n  insider_buy: 12\n"
        "  insider_sell: 10\n  analyst: 8\n  earnings_soon: 6\n  social: 10\n",
        encoding="utf-8")

    # AI "on" but no real API: dummy client + recorded/stubbed agents.
    monkeypatch.setattr(llm_mod, "AnthropicClient", lambda *a, **k: object())
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.social, "get_wsb_sentiment", lambda **kw: {})
    monkeypatch.setattr(main.congress, "get_congress_trades", lambda **kw: [])
    monkeypatch.setattr(main.congress, "aggregate_by_ticker",
                        lambda trades: {"AAA": {"net_side": "buy", "n_members": 3}})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    _stub_signal_feeds(monkeypatch)
    monkeypatch.setattr(main.news, "get_headlines", lambda t: ["a headline"])
    # AAA's BASE score is 59 -- below buy_threshold 65, but +18 congress projects it to 77.
    monkeypatch.setattr(main.scoring, "score_ticker",
                        lambda df, ticker, weights, settings: {
                            "ticker": ticker, "score": 59, "excluded": False,
                            "reason": "", "components": {"trend": 1.0}})
    called = {"news": [], "risk": []}
    monkeypatch.setattr(main.agents, "news_agent",
                        lambda client, ticker, headlines: (called["news"].append(ticker)
                                                           or dict(main.agents.NEUTRAL_NEWS)))
    monkeypatch.setattr(main.agents, "risk_agent",
                        lambda client, ticker, closes, headlines: (called["risk"].append(ticker)
                                                                   or dict(main.agents.NEUTRAL_RISK)))
    monkeypatch.setattr(main.agents, "context_agent", lambda *a, **k: {"regime": "neutral", "note": "n"})

    profile = Profile(
        config_dir=tmp_path / "config", data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        secrets=EnvSecrets(values={"ANTHROPIC_API_KEY": "sk-test"}),
    )
    fake_fetch = lambda ticker, lookback: helpers.make_df([10 + i * 0.1 for i in range(160)])

    main.run(profile=profile, force=True, fetch=fake_fetch)

    assert "AAA" in called["news"]   # boosted buy candidate got AI news (the fix)
    assert "AAA" in called["risk"]


def test_no_ai_run_labels_candidates_rules_only_not_unavailable(tmp_path, monkeypatch):
    """With no API key the candidate news/risk should read 'rules-only' (intentional skip),
    not 'news agent unavailable' (which now signals a genuine agent failure)."""
    from src import main
    _seed_min_config(tmp_path / "config")
    monkeypatch.setattr(main.social, "get_wsb_sentiment", lambda **kw: {})
    monkeypatch.setattr(main.congress, "get_congress_trades", lambda **kw: [])
    monkeypatch.setattr(main.congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    _stub_signal_feeds(monkeypatch)
    monkeypatch.setattr(main.news, "get_headlines", lambda t: [])

    fake_fetch = lambda ticker, lookback: helpers.make_df([10 + i * 0.1 for i in range(160)])
    profile = Profile(
        config_dir=tmp_path / "config", data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports", secrets=EnvSecrets(values={}),   # no key -> AI off
    )

    result = main.run(profile=profile, force=True, fetch=fake_fetch)

    assert "news agent unavailable" not in result.text
    assert "rules-only" in result.text


def test_skipped_views_score_identically_to_neutral_views():
    # The honest "rules-only" skip label must not change the score vs the old NEUTRAL_*
    # fallback — only the displayed text differs (guards a future edit that reads summary).
    from src import agents, adjudicator
    common = dict(congress={"net_side": "buy", "n_members": 2},
                  analyst={"rating": "buy", "upside_pct": 10}, thresholds=_THR,
                  social_view=dict(agents.NEUTRAL_SOCIAL))
    neutral = adjudicator.adjudicate(
        {"ticker": "X", "score": 50}, dict(agents.NEUTRAL_NEWS), dict(agents.NEUTRAL_RISK),
        _CTX, _CAPS, **common)
    skipped = adjudicator.adjudicate(
        {"ticker": "X", "score": 50}, dict(agents.SKIPPED_NEWS), dict(agents.SKIPPED_RISK),
        _CTX, _CAPS, **common)
    assert neutral["final_score"] == skipped["final_score"]


def _fake_fetch(ticker, lookback):
    n = max(lookback, 60)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    base = pd.Series(range(n), index=idx, dtype=float) + 100
    return pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1,
                         "Close": base, "Volume": 1_000_000.0}, index=idx)


def _stub_feeds(monkeypatch):
    """Make main.run fully offline+deterministic by neutralizing the network feeds."""
    monkeypatch.setattr(broker, "resolve_positions", lambda **kw: [])
    monkeypatch.setattr(social, "get_wsb_sentiment", lambda **kw: {})
    monkeypatch.setattr(congress, "get_congress_trades", lambda **kw: [])
    monkeypatch.setattr(congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(market, "get_market_breadth", lambda *a, **k: dict(market.NEUTRAL_BREADTH))
    monkeypatch.setattr(market, "get_macro_context", lambda *a, **k: dict(market.NEUTRAL_MACRO))
    monkeypatch.setattr(insights, "get_insider_signal", lambda ticker: None)
    monkeypatch.setattr(insights, "get_analyst_signal", lambda ticker: None)
    monkeypatch.setattr(insights, "get_earnings", lambda ticker: None)
    monkeypatch.setattr(insights, "get_short_signal", lambda ticker: None)
    monkeypatch.setattr(insights, "get_revision_signal", lambda ticker: None)
    monkeypatch.setattr(edgar, "load_cik_map", lambda **kw: {})
    monkeypatch.setattr(edgar, "get_sec_signal", lambda ticker, cik_map, **kw: None)
    monkeypatch.setattr(options, "get_options_signal", lambda ticker: None)


def test_objective_changes_effective_weights(tmp_path, monkeypatch):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    onboarding.set_objective(p, "aggressive")
    _stub_feeds(monkeypatch)

    seen = {}
    real = scoring.score_ticker
    def spy(df, ticker, weights, settings):
        seen["weights"] = weights
        return real(df, ticker, weights, settings)
    monkeypatch.setattr(scoring, "score_ticker", spy)

    main.run(profile=p, force=True, fetch=_fake_fetch)
    assert seen["weights"]["trend"] == 10        # aggressive preset, not the seeded 15
    assert seen["weights"]["pullback"] == 0
