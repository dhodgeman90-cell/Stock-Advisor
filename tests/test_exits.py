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
