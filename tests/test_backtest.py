import pandas as pd
from src import backtest
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


def test_summarize_handles_no_trades():
    s = backtest.summarize([])
    assert s["count"] == 0


def test_buy_and_hold_equal_weight_average():
    histories = {
        "A": make_df([100.0, 110.0]),    # +10%
        "B": make_df([100.0, 130.0]),    # +30%
    }
    assert round(backtest.buy_and_hold(histories), 1) == 20.0
