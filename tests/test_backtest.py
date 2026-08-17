import pandas as pd
from src import backtest
from src import data as _data
from tests.helpers import make_df

# Low buy_threshold (0) so any valid day triggers entry, letting us test the
# entry-timing and exit logic deterministically without hand-tuning a score.
RULES_ENTER_ALWAYS = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {"buy_threshold": 0, "max_hold_days": 60},
}
SETTINGS = {"min_price": 5.0, "min_avg_volume": 500_000}
WEIGHTS = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}


def test_simulate_ticker_closes_on_stop_loss_and_enters_next_day_open():
    # 62 flat days (so day 60 scores and triggers entry), then a drop to 92.
    prices = [100.0] * 62 + [92.0]               # index 62 close = 92 -> -8% stop
    df = make_df(prices)
    # Distinguish the entry day's open from its close to prove next-day-open entry.
    df.loc[df.index[61], "Open"] = 101.0
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, RULES_ENTER_ALWAYS)
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == 101.0             # entered at day-61 OPEN, not close
    assert t["reason"] == "stop_loss"
    assert round(t["return_pct"], 1) == round((92.0 - 101.0) / 101.0 * 100, 1)


# ---- enriched backtest (P0-a) ----

FULL_RULES = {
    "defaults": {"stop_loss_pct": 8, "take_profit_pct": 20, "take_profit_mode": "trailing",
                 "trailing_stop_pct": 12, "trend_break_fast": 20, "trend_break_slow": 50,
                 "trend_break_slow_level": "watch",
                 "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7}},
    "backtest": {"buy_threshold": 55, "max_hold_days": 60, "cost_pct_per_side": 0.0,
                 "stcg_tax_pct": 0},   # base ~45 misses; catalyst +15 -> 60 clears it
}
CAPS = {"edgar_catalyst": 15, "activist_stake": 12, "risk_high": 20, "risk_medium": 8,
        "regime": 5, "catalyst": 15, "news_negative": 10, "congress_buy": 18,
        "congress_sell": 18, "insider_buy": 12, "insider_sell": 10, "analyst": 8,
        "earnings_soon": 6, "social": 10, "options_flow": 8, "short_squeeze": 10,
        "estimate_revision": 5}
THRESH = {"sec_window_days": 30, "earnings_window_days": 5, "options_min_volume": 1000,
          "options_unusual_ratio": 0.5, "short_high_pct": 20, "social_min_mentions": 25}


def test_simulate_ticker_score_of_overrides_entry():
    df = make_df([100.0] * 70)                       # flat -> base score ~45
    rules = {**RULES_ENTER_ALWAYS, "backtest": {"buy_threshold": 90, "max_hold_days": 60}}
    assert backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules) == []   # base misses 90
    forced = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules,
                                      score_of=lambda w, t, res: 95.0)
    assert len(forced) == 1                          # score_of override forces the entry


def test_apply_tax_haircuts_gains_only():
    trades = [{"return_pct": 10.0, "reason": "x", "hold_days": 1},
              {"return_pct": -10.0, "reason": "y", "hold_days": 1}]
    out = backtest.apply_tax(trades, 25)
    assert out[0]["return_pct"] == 7.5               # 10 * (1 - 0.25)
    assert out[1]["return_pct"] == -10.0             # loss untouched
    assert backtest.apply_tax(trades, 0) == trades   # off = passthrough


def test_enriched_core_edgar_catalyst_triggers_trade_base_misses():
    # Flat price -> base score ~45 (< 60). An 8-K earnings catalyst dated on the decision
    # bar adds +15 -> 60, so ONLY the enriched engine enters; base never does.
    df = make_df([100.0] * 70)                       # bar index 60 == 2024-03-01
    histories = {"T": df}
    recent = {"T": {"form": ["8-K"], "items": ["2.02"], "filingDate": ["2024-03-01"]}}
    core = backtest.enriched_backtest_core(histories, recent, WEIGHTS, FULL_RULES, SETTINGS,
                                           CAPS, THRESH, presets=["balanced"], sec_window=30)
    p = core["per_preset"]["balanced"]
    assert p["enriched"]["summary"]["count"] == 1    # catalyst pushed 45 -> 60, entered
    assert p["base"]["summary"]["count"] == 0        # base alone never reached 60
    assert core["coverage_pct"] > 0 and core["n_names"] == 1


def test_render_enriched_report_states_verdict_and_disclaimer():
    core = {
        "per_preset": {"balanced": {
            "label": "Balanced", "tax_pct": 25,
            "enriched": {"summary": backtest.summarize(
                [{"return_pct": 5.0, "reason": "x", "hold_days": 1}]),
                "compounded": 5.0, "dd": -3.0},
            "base": {"summary": backtest.summarize([]), "compounded": 0.0}}},
        "baseline": 10.0, "buyhold_dd": -20.0, "coverage_pct": 30.0, "n_names": 1,
        "best_enriched": 5.0, "beat_buyhold": False,
    }
    text = backtest.render_enriched_report(core, "2026-07-06", years=4)
    assert "NO measured edge" in text and "Partial engine" in text
    assert "not financial advice" in text.lower()
    beat = backtest.render_enriched_report({**core, "best_enriched": 15.0, "beat_buyhold": True},
                                           "2026-07-06", years=4)
    assert "measured edge (partial)" in beat


# ---- average market exposure (% of trading bars invested) ----

def test_average_exposure_is_mean_time_in_market_across_names():
    # MIN_HISTORY warm-up bars can't hold a position, so usable = len(df) - MIN_HISTORY.
    hist = {"A": make_df([100.0] * (backtest.MIN_HISTORY + 100)),   # usable 100 bars
            "B": make_df([100.0] * (backtest.MIN_HISTORY + 50))}    # usable 50 bars
    trades = [{"ticker": "A", "hold_days": 30}, {"ticker": "A", "hold_days": 20},  # 50/100 = 50%
              {"ticker": "B", "hold_days": 10}]                                    # 10/50  = 20%
    assert round(backtest.average_exposure(hist, trades), 1) == 35.0   # mean(50%, 20%)


def test_average_exposure_counts_a_never_held_name_as_zero():
    hist = {"A": make_df([100.0] * (backtest.MIN_HISTORY + 100)),
            "B": make_df([100.0] * (backtest.MIN_HISTORY + 100))}    # usable 100 each
    trades = [{"ticker": "A", "hold_days": 50}]                      # A 50%, B never held -> 0%
    assert round(backtest.average_exposure(hist, trades), 1) == 25.0   # mean(50%, 0%)


def test_enriched_core_reports_exposure_per_preset():
    core = backtest.enriched_backtest_core({"T": make_df([100.0] * 70)}, {"T": {}}, WEIGHTS,
                                           FULL_RULES, SETTINGS, CAPS, THRESH,
                                           presets=["balanced"], sec_window=30)
    assert "exposure" in core["per_preset"]["balanced"]["enriched"]


def test_render_enriched_report_includes_exposure_column():
    core = {
        "per_preset": {"balanced": {
            "label": "Balanced", "tax_pct": 25,
            "enriched": {"summary": backtest.summarize(
                [{"return_pct": 5.0, "reason": "x", "hold_days": 1}]),
                "compounded": 5.0, "dd": -3.0, "exposure": 42.0},
            "base": {"summary": backtest.summarize([]), "compounded": 0.0}}},
        "baseline": 10.0, "buyhold_dd": -20.0, "coverage_pct": 30.0, "n_names": 1,
        "best_enriched": 5.0, "beat_buyhold": False,
    }
    text = backtest.render_enriched_report(core, "2026-07-06", years=4)
    assert "Exposure" in text          # new header cell
    assert "42%" in text               # the value, formatted as a percent


def test_render_enriched_report_shows_experiment_banner_before_table():
    core = {
        "per_preset": {"balanced": {
            "label": "Balanced", "tax_pct": 0,
            "enriched": {"summary": backtest.summarize([]), "compounded": 5.0, "dd": -3.0,
                         "exposure": 10.0},
            "base": {"summary": backtest.summarize([]), "compounded": 0.0}}},
        "baseline": 10.0, "buyhold_dd": -20.0, "coverage_pct": 30.0, "n_names": 1,
        "best_enriched": 5.0, "beat_buyhold": False,
    }
    text = backtest.render_enriched_report(core, "2026-07-06", years=4,
                                           banner="EXPERIMENT — stcg forced to 0")
    assert "EXPERIMENT" in text
    assert text.index("EXPERIMENT") < text.index("| Preset |")   # banner is up top
    # Omitted by default: real reports carry no experiment banner.
    assert "EXPERIMENT" not in backtest.render_enriched_report(core, "2026-07-06", years=4)


# ---- timing-matched market benchmark (isolates cash drag from signal) ----

def test_timing_matched_return_is_market_move_over_holding_windows():
    a = make_df([100.0, 105.0, 120.0])          # 2024-01-01 .. 01-03
    b = make_df([50.0, 60.0, 70.0])             # name B, never held -> 0%
    trades = [{"ticker": "A", "entry_date": "2024-01-01", "exit_date": "2024-01-03"}]  # +20%
    # A rode close 100 -> 120 over its window; B never held. mean(20%, 0%) = 10%.
    assert round(backtest.timing_matched_return({"A": a, "B": b}, trades), 1) == 10.0


def test_timing_matched_return_compounds_multiple_windows_for_a_name():
    a = make_df([100.0, 110.0, 110.0, 121.0])   # two windows: +10% then +10% -> compounds +21%
    trades = [{"ticker": "A", "entry_date": "2024-01-01", "exit_date": "2024-01-02"},
              {"ticker": "A", "entry_date": "2024-01-03", "exit_date": "2024-01-04"}]
    assert round(backtest.timing_matched_return({"A": a}, trades), 1) == 21.0


def test_enriched_core_reports_exposure_and_timing_per_preset():
    core = backtest.enriched_backtest_core({"T": make_df([100.0] * 70)}, {"T": {}}, WEIGHTS,
                                           FULL_RULES, SETTINGS, CAPS, THRESH,
                                           presets=["balanced"], sec_window=30)
    enr = core["per_preset"]["balanced"]["enriched"]
    assert "exposure" in enr and "timing" in enr


def test_render_enriched_report_states_pre_registered_signal_outcomes():
    core = {
        "per_preset": {"balanced": {
            "label": "Balanced", "tax_pct": 0,
            "enriched": {"summary": backtest.summarize([]), "compounded": 5.0, "dd": -3.0,
                         "exposure": 30.0, "timing": 8.0},
            "base": {"summary": backtest.summarize([]), "compounded": 0.0}}},
        "baseline": 10.0, "buyhold_dd": -20.0, "coverage_pct": 30.0, "n_names": 1,
        "best_enriched": 5.0, "beat_buyhold": False,
    }
    text = backtest.render_enriched_report(core, "2026-07-06", years=4)
    # All three outcome interpretations are present regardless of the numbers.
    assert "Attribution" in text
    assert "structural" in text            # S > 0 branch
    assert "unproven" in text              # S ~ 0 branch
    assert "anti-predictive" in text       # S < 0 branch


def test_simulate_ticker_no_trade_when_threshold_unreachable():
    prices = [100.0] * 70
    df = make_df(prices)
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 99, "max_hold_days": 60}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert trades == []


def test_summarize_computes_win_rate_and_averages():
    trades = [
        {"return_pct": 20.0, "hold_days": 10, "reason": "take_profit"},
        {"return_pct": -8.0, "hold_days": 3, "reason": "stop_loss"},
        {"return_pct": 12.0, "hold_days": 5, "reason": "take_profit"},
    ]
    s = backtest.summarize(trades)
    assert s["count"] == 3
    assert round(s["win_rate"], 1) == 66.7
    assert round(s["avg_gain"], 1) == 16.0
    assert round(s["avg_loss"], 1) == -8.0
    assert s["by_reason"]["take_profit"] == 2
    assert round(s["avg_trade_return"], 1) == 8.0


def test_summarize_handles_no_trades():
    s = backtest.summarize([])
    assert s["count"] == 0


def test_buy_and_hold_equal_weight_average():
    histories = {
        "A": make_df([100.0, 110.0]),    # +10%
        "B": make_df([100.0, 130.0]),    # +30%
    }
    assert round(backtest.buy_and_hold(histories), 1) == 20.0


def test_simulate_ticker_force_closes_at_max_hold():
    prices = [100.0] * 70           # flat: no stop/target/trend/fade ever fires
    df = make_df(prices)
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 3}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert len(trades) >= 1
    assert trades[0]["reason"] == "max_hold"
    assert trades[0]["hold_days"] == 3


def test_simulate_ticker_force_closes_open_trade_at_end_of_data():
    prices = [100.0] * 63           # entry at day 61; data ends before any exit
    df = make_df(prices)
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 60}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert len(trades) == 1
    assert trades[0]["reason"] == "end_of_data"


RULES_TRAILING = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "take_profit_mode": "trailing",
        "trailing_stop_pct": 15,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {"buy_threshold": 0, "max_hold_days": 600},
}


def test_simulate_ticker_lets_winner_run_then_trailing_stops():
    # 62 flat days (entry triggers), climb to 200, then fall 16% off the peak.
    prices = [100.0] * 62 + list(range(100, 201, 5)) + [184.0, 168.0]
    df = make_df([float(p) for p in prices])
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, RULES_TRAILING)
    assert len(trades) == 1
    assert trades[0]["reason"] == "trailing_stop"
    assert trades[0]["return_pct"] > 20.0          # rode well past the old +20% cap


def test_transaction_cost_reduces_return():
    prices = [100.0] * 62 + [92.0]                 # -8% stop, hard mode
    df = make_df(prices)
    df.loc[df.index[61], "Open"] = 100.0           # entry at 100 for clean math
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 60, "cost_pct_per_side": 0.5}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    raw = (92.0 - 100.0) / 100.0 * 100             # -8.0
    assert round(trades[0]["return_pct"], 2) == round(raw - 1.0, 2)   # minus 2*0.5% round-trip


def test_zero_cost_matches_raw_return():
    prices = [100.0] * 62 + [92.0]
    df = make_df(prices)
    df.loc[df.index[61], "Open"] = 100.0
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 60, "cost_pct_per_side": 0.0}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert round(trades[0]["return_pct"], 2) == -8.0


def test_render_backtest_report_lists_trades_and_baseline():
    trades = [{"ticker": "AAA", "entry_date": "2024-01-01", "exit_date": "2024-01-05",
               "entry_price": 100.0, "exit_price": 108.0, "return_pct": 8.0,
               "hold_days": 4, "reason": "take_profit"}]
    summary = backtest.summarize(trades)
    text = backtest.render_backtest_report(summary, 5.0, trades, "2026-06-08")
    assert "AAA" in text
    assert "take profit" in text
    assert "Buy-and-hold baseline" in text
    assert "Avg return per trade" in text
    assert "not financial advice" in text.lower()


def test_compounded_per_name_compounds_then_averages():
    trades = [
        {"ticker": "A", "return_pct": 10.0},   # A: 1.10 * 1.10 = 1.21 -> +21%
        {"ticker": "A", "return_pct": 10.0},
        {"ticker": "B", "return_pct": -50.0},  # B: -50%
    ]
    # average of +21% and -50% = -14.5%
    assert round(backtest.compounded_per_name(trades), 1) == -14.5


def test_compounded_per_name_empty():
    assert backtest.compounded_per_name([]) == 0.0


def test_summarize_includes_expectancy():
    trades = [
        {"return_pct": 20.0, "hold_days": 10, "reason": "take_profit"},
        {"return_pct": -8.0, "hold_days": 3, "reason": "stop_loss"},
    ]
    s = backtest.summarize(trades)
    # 0.5*20 + 0.5*(-8) = 6.0
    assert round(s["expectancy"], 1) == 6.0


def test_load_history_uses_cache_when_fetch_fails(monkeypatch, tmp_path):
    good = make_df([100.0] * 60)
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: (_ for _ in ()).throw(RuntimeError("net down")))
    monkeypatch.setattr(_data, "load_cache", lambda t, dd: good)
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "cache"
    assert df is not None


def test_load_history_skips_when_no_data_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: None)
    monkeypatch.setattr(_data, "load_cache", lambda t, dd: None)
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "skipped"
    assert df is None


def test_load_history_saves_cache_on_live_success(monkeypatch, tmp_path):
    good = make_df([100.0] * 60)
    saved = {}
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: good)
    monkeypatch.setattr(_data, "save_cache", lambda df, t, dd: saved.update({t: True}))
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "live"
    assert saved.get("T") is True


def test_report_drops_misleading_sum_and_shows_compounded():
    trades = [{"ticker": "AAA", "entry_date": "2024-01-01", "exit_date": "2024-01-05",
               "entry_price": 100.0, "exit_price": 108.0, "return_pct": 8.0,
               "hold_days": 4, "reason": "trailing_stop"}]
    summary = backtest.summarize(trades)
    text = backtest.render_backtest_report(summary, 5.0, trades, "2026-06-08")
    assert "Sum of all" not in text                       # misleading headline removed
    assert "compounded" in text.lower()
    assert "Expectancy" in text


def test_max_drawdown_flat_is_zero():
    assert backtest.max_drawdown([100.0, 100.0, 100.0]) == 0.0


def test_max_drawdown_monotonic_up_is_zero():
    assert backtest.max_drawdown([100.0, 110.0, 130.0]) == 0.0


def test_max_drawdown_simple_dip():
    # peak 100 -> trough 70 = -30%
    assert round(backtest.max_drawdown([100.0, 70.0, 90.0]), 1) == -30.0


def test_max_drawdown_picks_worst_after_recovery():
    # 100 -> 90 (-10%), recover to 120, drop to 84 (-30% off the new peak 120)
    assert round(backtest.max_drawdown([100.0, 90.0, 120.0, 84.0]), 1) == -30.0


def test_max_drawdown_empty_is_zero():
    assert backtest.max_drawdown([]) == 0.0


def test_strategy_equity_curve_tracks_trade_then_flat_in_cash():
    # Hold from 01-02 to 01-04 (+20%), then sit in cash flat at 1.20.
    df = make_df([100.0, 100.0, 110.0, 120.0, 120.0, 120.0])
    trades = [{"ticker": "T", "entry_date": "2024-01-02", "exit_date": "2024-01-04",
               "entry_price": 100.0, "exit_price": 120.0, "return_pct": 20.0,
               "hold_days": 2, "reason": "take_profit"}]
    curve = backtest.strategy_equity_curve({"T": df}, trades)
    assert [round(v, 3) for v in curve] == [1.0, 1.0, 1.1, 1.2, 1.2, 1.2]


def test_strategy_equity_curve_averages_equal_weight_across_tickers():
    a = make_df([100.0, 100.0, 120.0])           # A trades +20% over the window
    b = make_df([100.0, 100.0, 100.0])           # B never trades -> flat at 1.0
    trades = [{"ticker": "A", "entry_date": "2024-01-01", "exit_date": "2024-01-03",
               "entry_price": 100.0, "exit_price": 120.0, "return_pct": 20.0,
               "hold_days": 2, "reason": "take_profit"}]
    curve = backtest.strategy_equity_curve({"A": a, "B": b}, trades)
    # A slice [1.0, 1.0, 1.2]; B slice [1.0, 1.0, 1.0]; mean [1.0, 1.0, 1.1]
    assert [round(v, 3) for v in curve] == [1.0, 1.0, 1.1]


def test_strategy_equity_curve_empty_histories():
    assert backtest.strategy_equity_curve({}, []) == []


def test_buy_and_hold_equity_curve_equal_weight():
    a = make_df([100.0, 110.0, 120.0])           # normalized [1.0, 1.1, 1.2]
    b = make_df([100.0, 100.0, 80.0])            # normalized [1.0, 1.0, 0.8]
    curve = backtest.buy_and_hold_equity_curve({"A": a, "B": b})
    assert [round(v, 3) for v in curve] == [1.0, 1.05, 1.0]


def test_report_includes_max_drawdown_lines():
    trades = [{"ticker": "AAA", "entry_date": "2024-01-01", "exit_date": "2024-01-05",
               "entry_price": 100.0, "exit_price": 108.0, "return_pct": 8.0,
               "hold_days": 4, "reason": "take_profit"}]
    summary = backtest.summarize(trades)
    text = backtest.render_backtest_report(summary, 5.0, trades, "2026-06-08",
                                           strategy_dd=-9.0, buyhold_dd=-28.0)
    assert "Strategy max drawdown: **-9.0%**" in text
    assert "Buy-and-hold max drawdown: **-28.0%**" in text


# ---- per-regime summary (Phase 0) ----

def _long_flat_df(start="2021-06-01", periods=1400, price=100.0):
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame({"Open": price, "High": price, "Low": price,
                         "Close": price, "Volume": 1_000_000}, index=idx)


def test_per_regime_summary_runs_each_window_with_enough_data():
    histories = {"T": _long_flat_df()}               # 2021-06 .. ~2025-04, spans every window
    out = backtest.per_regime_summary(histories, {"T": {}}, WEIGHTS, FULL_RULES, SETTINGS,
                                      CAPS, THRESH, presets=["balanced"], sec_window=30)
    assert "full" in out and "2022_selloff" in out
    assert "per_preset" in out["full"] and "baseline" in out["full"]


def test_per_regime_summary_isolates_a_down_regime():
    # Price falls across 2022 (~100 -> ~60), recovers after. The 2022 slice's buy-and-hold
    # baseline must be negative even though the full cycle recovers.
    idx = pd.date_range("2021-06-01", periods=1400, freq="D")
    prices = []
    for ts in idx:
        if ts.year < 2022:
            prices.append(100.0)
        elif ts.year == 2022:
            prices.append(100.0 - 0.11 * ts.dayofyear)   # ~100 in Jan -> ~60 by Dec
        else:
            prices.append(60.0 + 0.03 * ts.dayofyear)
    df = pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                       "Close": prices, "Volume": 1_000_000}, index=idx)
    out = backtest.per_regime_summary({"T": df}, {"T": {}}, WEIGHTS, FULL_RULES, SETTINGS,
                                      CAPS, THRESH, presets=["balanced"], sec_window=30)
    assert out["2022_selloff"]["baseline"] < 0


def test_render_enriched_report_appends_per_regime_table_when_given():
    core = {
        "per_preset": {"balanced": {
            "label": "Balanced", "tax_pct": 0,
            "enriched": {"summary": backtest.summarize([]), "compounded": 3.0, "dd": -5.0},
            "base": {"summary": backtest.summarize([]), "compounded": 0.0}}},
        "baseline": 10.0, "buyhold_dd": -20.0, "coverage_pct": 30.0, "n_names": 1,
        "best_enriched": 3.0, "beat_buyhold": False,
    }
    text = backtest.render_enriched_report(core, "2026-07-27", years=6,
                                           per_regime={"2022_selloff": core, "full": core})
    assert "Per-regime" in text and "2022" in text
    # Without per_regime the section is omitted (existing callers unchanged).
    assert "Per-regime" not in backtest.render_enriched_report(core, "2026-07-27", years=6)
