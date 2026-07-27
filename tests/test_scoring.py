import pandas as pd

from src import scoring
from tests.helpers import make_df

WEIGHTS = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
SETTINGS = {"min_price": 5.0, "min_avg_volume": 500_000}


def test_uptrend_is_not_excluded_and_fires_strong_signals():
    # 80 strictly-increasing closes from 50. This is a strong trend AND a fresh
    # breakout, so those components should max out. Note: a straight-up climb is
    # "overbought" (RSI ~100), so the momentum component is intentionally
    # withheld -- the engine penalizes parabolic moves. Net score lands mid-high.
    df = make_df(list(range(50, 130)))
    result = scoring.score_ticker(df, "TEST", WEIGHTS, SETTINGS)
    assert result["excluded"] is False
    assert result["components"]["trend"] == 1.0        # clear uptrend
    assert result["components"]["breakout"] >= 0.99     # at new highs (float-safe)
    assert result["components"]["momentum"] == 0.0      # overbought -> penalized
    assert result["score"] >= 50
    assert set(result["components"]) == {
        "trend", "momentum", "breakout", "volume", "pullback"
    }


def test_penny_stock_is_excluded_by_price_floor():
    df = make_df([2.0] * 60)            # below $5 floor
    result = scoring.score_ticker(df, "PENNY", WEIGHTS, SETTINGS)
    assert result["excluded"] is True
    assert "price" in result["reason"].lower()


def test_illiquid_stock_is_excluded_by_volume_floor():
    df = make_df(list(range(50, 110)), volume=1_000)   # tiny volume
    result = scoring.score_ticker(df, "THIN", WEIGHTS, SETTINGS)
    assert result["excluded"] is True
    assert "volume" in result["reason"].lower()


def test_high_priced_thin_share_count_is_liquid_in_dollars():
    # NVR-style: only ~30k shares/day, but at ~$8k/share that's ~$240M/day — very liquid.
    # The old share-count floor (500k) wrongly excluded it; the dollar-volume gate keeps it.
    df = make_df([8000.0] * 60, volume=30_000)
    result = scoring.score_ticker(df, "NVR", WEIGHTS,
                                  {"min_price": 5.0, "min_dollar_volume": 10_000_000})
    assert result["excluded"] is False


# ---- relative-strength entry model (Phase 3) ----

def _fresh_high_2x_volume():
    """Steady uptrend whose last bar is a fresh 20-day high on a 2x volume spike."""
    prices = [100.0 + i for i in range(60)]              # 100..159, last is the max
    vol = [1_000_000] * 59 + [2_000_000]
    idx = pd.date_range("2023-01-01", periods=60, freq="D")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": vol}, index=idx)


def _constructive_pullback_uptrend():
    """Uptrend for 55 bars, then a shallow ~5% pullback over the last 5 bars."""
    up = [100.0 + i for i in range(55)]                  # 100..154
    peak = up[-1]
    pull = [peak * (1 - 0.01 * j) for j in range(1, 6)]  # ~1%..5% below the peak
    prices = up + pull
    idx = pd.date_range("2023-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": [1_000_000] * len(prices)}, index=idx)


def test_relative_strength_matches_return_difference():
    name = pd.Series([100.0] * 10 + [110.0])             # +10% over the lookback
    spy = pd.Series([100.0] * 10 + [104.0])              # +4%
    assert round(scoring.relative_strength(name, spy, lookback=10), 2) == 6.0


def test_relative_strength_zero_when_too_short():
    s = pd.Series([100.0, 101.0])
    assert scoring.relative_strength(s, s, lookback=63) == 0.0


def test_cross_sectional_rank_orders_by_strength():
    r = scoring.cross_sectional_rank({"A": 30.0, "B": 20.0, "C": 10.0})
    assert r["A"] == 1.0 and r["B"] == 0.5 and r["C"] == 0.0


def test_cross_sectional_rank_ignores_none_values():
    r = scoring.cross_sectional_rank({"A": 5.0, "B": None})
    assert set(r) == {"A"}


def test_constructive_pullback_rewards_dip_in_uptrend():
    assert scoring.constructive_pullback(_constructive_pullback_uptrend()) > 0.7


def test_constructive_pullback_zero_in_downtrend():
    assert scoring.constructive_pullback(make_df([200.0 - i for i in range(60)])) == 0.0


def test_rs_entry_flips_the_breakout_chasing_inversion():
    breakout = _fresh_high_2x_volume()
    pullback = _constructive_pullback_uptrend()
    # Legacy over-rewards the fresh-high-on-2x-volume breakout (the inverted top band):
    lb = scoring.score_ticker(breakout, "BRK", WEIGHTS, SETTINGS)["score"]
    lp = scoring.score_ticker(pullback, "PUL", WEIGHTS, SETTINGS)["score"]
    assert lb > lp
    # RS entry with EQUAL relative strength ranks the constructive pullback ABOVE the chase:
    assert scoring.rs_entry_rank(pullback, 0.5) > scoring.rs_entry_rank(breakout, 0.5)
