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
