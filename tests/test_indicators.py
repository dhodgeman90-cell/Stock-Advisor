import pandas as pd
from src import indicators
from tests.helpers import make_df


def test_sma_last_value():
    s = pd.Series([1, 2, 3, 4, 5])
    assert indicators.sma(s, 3).iloc[-1] == 4.0   # (3+4+5)/3


def test_rsi_all_gains_is_100():
    # strictly increasing close -> no losses -> RSI = 100
    close = pd.Series(range(1, 40))
    assert round(indicators.rsi(close, 14).iloc[-1], 2) == 100.0


def test_breakout_strength_at_high_is_one():
    close = pd.Series([10, 11, 12])   # latest == rolling max
    assert indicators.breakout_strength(close, 3) == 1.0


def test_volume_ratio_double_average():
    # last 3 volumes: 100, 100, 400 -> avg 200, latest 400 -> ratio 2.0
    vol = pd.Series([100, 100, 100, 400])
    assert round(indicators.volume_ratio(vol, 3), 2) == 2.0
