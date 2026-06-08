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
