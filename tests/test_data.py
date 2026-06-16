import datetime as dt

import pandas as pd

from src import data
from tests.helpers import make_df


def _df_with_volume_only_trailing_bar(prices):
    """A valid history plus a yfinance-style placeholder last bar: volume present,
    OHLC all NaN. This is exactly what poisoned AAPL/SOXL/... this morning."""
    df = make_df(prices)
    last = df.index[-1] + pd.Timedelta(days=1)
    df.loc[last] = [float("nan"), float("nan"), float("nan"), float("nan"), 999_999]
    return df


def test_validate_accepts_good_data():
    df = make_df(list(range(50, 120)))   # 70 rows, valid prices
    ok, reason = data.validate(df, "GOOD")
    assert ok is True
    assert reason == ""


def test_validate_rejects_too_few_rows():
    df = make_df([10, 11, 12])           # only 3 rows
    ok, reason = data.validate(df, "SHORT")
    assert ok is False
    assert "rows" in reason.lower()


def test_validate_rejects_nonpositive_close():
    df = make_df([10, 0, 12] + list(range(13, 70)))   # contains a 0 close
    ok, reason = data.validate(df, "ZERO")
    assert ok is False


def test_cache_round_trip(tmp_path):
    df = make_df(list(range(50, 120)))
    data.save_cache(df, "RT", tmp_path)
    loaded = data.load_cache("RT", tmp_path)
    assert loaded is not None
    assert list(loaded["Close"]) == list(df["Close"])


def test_load_cache_missing_returns_none(tmp_path):
    assert data.load_cache("NOPE", tmp_path) is None


def test_drop_incomplete_removes_volume_only_trailing_bar():
    df = _df_with_volume_only_trailing_bar(list(range(50, 120)))   # 70 good + 1 NaN bar
    cleaned = data._drop_incomplete(df)
    assert len(cleaned) == len(df) - 1
    assert not pd.isna(cleaned["Close"].iloc[-1])


def test_validate_rejects_nan_last_close():
    # Backstop: even if a NaN trailing bar slips past _drop_incomplete, validate must
    # reject it rather than let close.iloc[-1] become NaN (the "price unavailable" bug).
    df = _df_with_volume_only_trailing_bar(list(range(50, 120)))
    ok, reason = data.validate(df, "NANLAST")
    assert ok is False


def test_load_cache_heals_poisoned_trailing_bar(tmp_path):
    # Reproduces this morning's cache files: a valid CSV with a volume-only last row.
    df = make_df(list(range(50, 120)))
    data.save_cache(df, "HEAL", tmp_path)
    with open(data.cache_path("HEAL", tmp_path), "a", encoding="utf-8") as f:
        f.write("2099-01-01,,,,,999999\n")
    loaded = data.load_cache("HEAL", tmp_path)
    assert len(loaded) == len(df)
    assert not pd.isna(loaded["Close"].iloc[-1])


def test_window_bounds_honors_days_plus_warmup():
    today = dt.date(2026, 6, 8)
    start, end = data._window_bounds(730, today=today, warmup=100)
    assert start == "2024-02-29"          # 2026-06-08 minus 830 days (730 + 100 warmup)
    assert end == "2026-06-09"            # today + 1 day (yfinance end is exclusive)
