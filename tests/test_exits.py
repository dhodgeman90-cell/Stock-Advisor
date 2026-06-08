import pandas as pd
from src import exits
from tests.helpers import make_df

RULES = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {},
}


def _types(result):
    return [s["type"] for s in result["signals"]]


def test_stop_loss_fires_alone_on_steady_uptrend_below_entry():
    # Steady uptrend so price is ABOVE both MAs (no trend break); RSI still
    # climbing (no fade); we just bought too high so we're 8%+ underwater.
    df = make_df(list(range(50, 110)))           # last close = 109
    position = {"ticker": "T", "entry_price": 119.0}   # 109 is ~8.4% below 119
    result = exits.evaluate_exit(df, position, RULES)
    assert _types(result) == ["stop_loss"]
    assert result["pct_from_entry"] < 0


def test_take_profit_fires_when_up_target():
    df = make_df(list(range(50, 110)))           # last close = 109
    position = {"ticker": "T", "entry_price": 90.0}    # 109 is ~21% above 90
    result = exits.evaluate_exit(df, position, RULES)
    assert _types(result) == ["take_profit"]


def test_trend_break_lists_slow_before_fast():
    # Rise then fall below both moving averages, but only ~3% below entry
    # (so stop-loss does NOT fire).
    prices = list(range(50, 101)) + [95, 90, 85, 80, 78, 76, 74, 72, 70, 68]
    df = make_df(prices)                          # last close = 68
    position = {"ticker": "T", "entry_price": 70.0}    # 68 is ~2.9% below entry
    result = exits.evaluate_exit(df, position, RULES)
    types = _types(result)
    assert "trend_break_slow" in types
    assert "trend_break_fast" in types
    assert types.index("trend_break_slow") < types.index("trend_break_fast")
    assert "stop_loss" not in types


def test_momentum_fade_fires_on_rolling_rsi_and_dry_volume():
    prices = list(range(50, 106)) + [104, 103, 102, 101]   # peak then roll over
    vols = [1_000_000] * (len(prices) - 1) + [150_000]      # volume dries up
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    df = pd.DataFrame(
        {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": vols},
        index=idx,
    )
    position = {"ticker": "T", "entry_price": 100.0}        # ~1% up: no stop/target
    result = exits.evaluate_exit(df, position, RULES)
    assert "momentum_fade" in _types(result)


def test_per_position_override_suppresses_default_stop():
    df = make_df(list(range(50, 110)))            # last close = 109
    position = {"ticker": "T", "entry_price": 121.0, "stop_loss_pct": 15}
    # 109 is ~9.9% below 121 -> default 8% would fire, but override 15% does not
    result = exits.evaluate_exit(df, position, RULES)
    assert "stop_loss" not in _types(result)


def test_clean_holding_returns_no_signals():
    df = make_df(list(range(50, 110)))            # uptrend, price above MAs
    position = {"ticker": "T", "entry_price": 108.0}   # ~0.9% up
    result = exits.evaluate_exit(df, position, RULES)
    assert result["signals"] == []


TRAIL_RULES = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "take_profit_mode": "trailing",
        "trailing_stop_pct": 15,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {},
}


def test_trailing_stop_fires_on_pullback_from_peak():
    # Price well above entry and above MAs, but 15%+ below the peak we pass in.
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 70.0, "peak_price": 130.0}
    # 109 is ~16% below peak 130 -> trailing stop fires; not below MAs, not -8% from entry
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" in _types(result)
    assert "take_profit" not in _types(result)               # hard target suppressed in trailing mode


def test_trailing_stop_silent_while_near_peak():
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 70.0, "peak_price": 110.0}
    # 109 is <1% below peak 110 -> no trailing stop
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" not in _types(result)


def test_trailing_mode_still_honors_hard_stop_loss():
    # Steady uptrend, bought too high -> -8% stop must still fire even in trailing mode.
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 119.0, "peak_price": 119.0}
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "stop_loss" in _types(result)


def test_trailing_stop_falls_back_to_entry_when_no_peak_given():
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 100.0}         # no peak_price; 109 > entry
    # peak falls back to max(entry, price)=109; 109 not 15% below 109 -> no trailing stop, no crash
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" not in _types(result)


def test_trend_break_slow_level_defaults_to_sell():
    prices = list(range(50, 101)) + [95, 90, 85, 80, 78, 76, 74, 72, 70, 68]
    df = make_df(prices)                                      # last close = 68, below MAs
    position = {"ticker": "T", "entry_price": 70.0}          # ~2.9% below entry: no stop
    result = exits.evaluate_exit(df, position, RULES)        # RULES has no level key
    sig = next(s for s in result["signals"] if s["type"] == "trend_break_slow")
    assert sig["level"] == "sell"


def test_trend_break_slow_level_configurable_to_watch():
    prices = list(range(50, 101)) + [95, 90, 85, 80, 78, 76, 74, 72, 70, 68]
    df = make_df(prices)
    position = {"ticker": "T", "entry_price": 70.0}
    rules = {**RULES, "defaults": {**RULES["defaults"], "trend_break_slow_level": "watch"}}
    result = exits.evaluate_exit(df, position, rules)
    sig = next(s for s in result["signals"] if s["type"] == "trend_break_slow")
    assert sig["level"] == "watch"                            # demoted -> won't close a backtest trade
