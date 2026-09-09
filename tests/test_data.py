import datetime as dt

import pandas as pd
import pytest

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


# ---- partial (still-trading) bar ----------------------------------------
# yfinance serves a live intraday bar for the CURRENT session with real OHLC and only
# part of the day's volume. It passes the NaN check above, then indicators.volume_ratio
# divides that part-day volume by a full-day 20-day average — and `volume` is 30 of the
# 100 base points. Measured on 2026-07-27: the top-8 shortlist built from partial bars
# overlapped the clean one by 1 of 8.

def _et(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=data.MARKET_TZ)


def _df_ending(last_date, n=70):
    idx = pd.date_range(end=pd.Timestamp(last_date), periods=n, freq="B")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
                         "Volume": 1_000_000}, index=idx)


def test_drop_incomplete_removes_todays_bar_before_the_close():
    df = _df_ending("2026-07-27")
    cleaned = data._drop_incomplete(df, now=_et(2026, 7, 27, 8, 50))   # mid-session
    assert len(cleaned) == len(df) - 1
    assert cleaned.index[-1].date() == dt.date(2026, 7, 24)


def test_drop_incomplete_keeps_todays_bar_after_the_close():
    df = _df_ending("2026-07-27")
    cleaned = data._drop_incomplete(df, now=_et(2026, 7, 27, 16, 30))  # post-close
    assert len(cleaned) == len(df)
    assert cleaned.index[-1].date() == dt.date(2026, 7, 27)


def test_drop_incomplete_keeps_a_completed_prior_session():
    df = _df_ending("2026-07-24")
    cleaned = data._drop_incomplete(df, now=_et(2026, 7, 27, 8, 50))
    assert len(cleaned) == len(df)   # yesterday's bar is final regardless of the clock


def test_drop_incomplete_strips_every_trailing_incomplete_bar():
    # A future-dated bar (clock skew / bad cache) must go too, not just today's.
    df = _df_ending("2026-07-29")
    cleaned = data._drop_incomplete(df, now=_et(2026, 7, 27, 8, 50))
    assert cleaned.index[-1].date() == dt.date(2026, 7, 24)


def test_load_cache_strips_a_cached_partial_bar(tmp_path):
    # The 2026-07-27 08:50 run wrote partial bars into ~570 cache files. Reading one back
    # must heal it, not re-ingest it.
    data.save_cache(_df_ending("2026-07-27"), "PARTIAL", tmp_path)
    cleaned = data.load_cache("PARTIAL", tmp_path, now=_et(2026, 7, 27, 8, 50))
    assert cleaned.index[-1].date() == dt.date(2026, 7, 24)


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


# ================== save_cache must never shrink the history ==================
# Root cause of "no backtest in this repo can measure the strategy that actually runs":
# save_cache was a plain df.to_csv() overwrite, and the daily run refetches only
# lookback_days(200) + WARMUP_DAYS(100) = 300 calendar days. So every morning's briefing
# destroyed the 7 years scripts/fetch_deep_history.py had pulled. Measured 2026-09-09:
# 589 cached CSVs, median 204 bars, only 3 of 589 with >= 252. score_panel.load_panel
# (min_bars=800) returned an empty panel and event_study.py could not start.

def _span(start, periods, price, volume=1_000_000):
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price,
                         "Volume": volume}, index=idx)


def test_a_short_refetch_does_not_destroy_the_deep_history(tmp_path):
    deep = _span("2020-01-01", 800, 100.0)
    data.save_cache(deep, "AAA", tmp_path)
    fresh = _span("2022-02-14", 300, 100.0)          # the daily 300-day window
    data.save_cache(fresh, "AAA", tmp_path)
    out = data.load_cache("AAA", tmp_path)
    assert len(out) >= 800, "the daily run must never shrink the cache"
    assert out.index[0] == deep.index[0]             # the old head survives
    assert out.index[-1] == fresh.index[-1]          # and the new tail lands


def test_new_bars_are_appended_and_overlapping_dates_prefer_the_fresh_values(tmp_path):
    data.save_cache(_span("2024-01-01", 100, 10.0), "AAA", tmp_path)
    data.save_cache(_span("2024-03-11", 100, 11.0), "AAA", tmp_path)   # overlaps + extends
    out = data.load_cache("AAA", tmp_path)
    assert len(out) == 170
    assert float(out["Close"].iloc[-1]) == 11.0
    assert float(out["Close"].loc["2024-03-11"]) == 11.0   # fresh wins on a shared date


def test_a_split_readjustment_is_rescaled_instead_of_spliced_into_a_fake_gap(tmp_path):
    # yfinance fetches with auto_adjust=True, so a 2:1 split re-adjusts the ENTIRE series.
    # Naively keeping the old rows would leave a 2x price cliff at the seam and fabricate a
    # -50% return. The old tail must be rescaled onto the new basis instead.
    data.save_cache(_span("2024-01-01", 400, 100.0, volume=1_000_000), "AAA", tmp_path)
    post_split = _span("2024-11-26", 200, 50.0, volume=2_000_000)     # every price halved
    data.save_cache(post_split, "AAA", tmp_path)
    out = data.load_cache("AAA", tmp_path)
    assert len(out) >= 400
    closes = out["Close"]
    assert float(closes.iloc[0]) == pytest.approx(50.0)      # old head rescaled onto the new basis
    assert float(closes.max()) == pytest.approx(50.0)        # and no cliff anywhere
    assert float(out["Volume"].iloc[0]) == pytest.approx(2_000_000)   # volume scales inversely


def test_an_incoherent_overlap_keeps_the_fresh_frame_rather_than_guessing(tmp_path):
    # If the overlap does not agree on a single constant ratio, this is not a re-adjustment --
    # it is bad data. Splicing anyway would invent prices, so the fresh frame stands alone.
    data.save_cache(_span("2024-01-01", 200, 100.0), "AAA", tmp_path)
    noisy = _span("2024-05-20", 200, 100.0)
    noisy.loc[noisy.index[:40], ["Open", "High", "Low", "Close"]] = 5.0    # nonsense overlap
    data.save_cache(noisy, "AAA", tmp_path)
    out = data.load_cache("AAA", tmp_path)
    assert out.index[0] == noisy.index[0]      # no fabricated history
    assert len(out) == len(noisy)


def test_saving_into_an_empty_directory_still_works(tmp_path):
    data.save_cache(_span("2024-01-01", 60, 10.0), "NEW", tmp_path)
    assert len(data.load_cache("NEW", tmp_path)) == 60
