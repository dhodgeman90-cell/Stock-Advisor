"""Phase B — the score-defect fixes: positive-stack cap, freshness gates, Wilder RSI, ATR stop."""
import datetime as dt

import pandas as pd

from src import adjudicator, indicators, exits

NEWS = {"catalyst": False, "sentiment": "neutral", "summary": ""}
POS_NEWS = {"catalyst": True, "sentiment": "pos", "summary": ""}
RISK = {"risk_level": "low", "veto": False, "reason": ""}
CTX = {"regime": "neutral"}
CAPS = {"risk_high": 20, "risk_medium": 8, "catalyst": 15, "news_negative": 10, "regime": 5,
        "congress_buy": 18, "congress_sell": 18, "insider_buy": 12, "insider_sell": 10,
        "analyst": 8, "earnings_soon": 6, "social": 10, "edgar_catalyst": 15,
        "activist_stake": 12, "options_flow": 8, "short_squeeze": 10, "estimate_revision": 5}


# ---- positive-stack cap --------------------------------------------------
def test_weak_base_cannot_be_stacked_to_a_buy():
    # A mediocre 45 chart with six positive signals piled on. Raw sum would be ~76 -> ~100+.
    out = adjudicator.adjudicate(
        {"ticker": "X", "score": 45}, POS_NEWS, RISK, CTX, CAPS,
        congress={"net_side": "buy", "n_members": 2, "fresh": True},
        insider={"net_side": "buy"}, analyst={"rating": "buy", "upside_pct": 10},
        edgar={"catalyst": True, "catalyst_types": ["deal"]},
        options={"call_volume": 5000, "put_volume": 500, "vol_oi_ratio": 1.0, "direction": "bullish"},
        thresholds={})
    assert out["final_score"] < 76          # capped well below the naive stack
    assert out["final_score"] > 45          # still boosted — just with diminishing returns


def test_single_signal_is_not_penalised_by_the_cap():
    out = adjudicator.adjudicate({"ticker": "X", "score": 60}, POS_NEWS, RISK, CTX, CAPS,
                                 thresholds={})
    assert out["final_score"] == 75         # a lone +15 catalyst still counts in full


# ---- freshness gates -----------------------------------------------------
def test_stale_congress_does_not_fire():
    out = adjudicator.adjudicate({"ticker": "X", "score": 50}, NEWS, RISK, CTX, CAPS,
                                 congress={"net_side": "buy", "n_members": 1, "fresh": False},
                                 thresholds={})
    assert out["final_score"] == 50
    assert not any("congress" in a for a in out["adjustments"])


def test_fresh_congress_still_fires():
    out = adjudicator.adjudicate({"ticker": "X", "score": 50}, NEWS, RISK, CTX, CAPS,
                                 congress={"net_side": "buy", "n_members": 1, "fresh": True},
                                 thresholds={})
    assert out["final_score"] == 68         # +18


def test_stale_short_does_not_fire_squeeze():
    out = adjudicator.adjudicate({"ticker": "X", "score": 70}, NEWS, RISK, CTX, CAPS,
                                 short={"pct_float": 30, "fresh": False},
                                 thresholds={"short_high_pct": 20})
    assert out["final_score"] == 70


# ---- Wilder RSI ----------------------------------------------------------
def test_rsi_all_losses_is_zero():
    close = pd.Series(range(40, 1, -1))     # strictly decreasing -> RSI 0
    assert indicators.rsi(close, 14).iloc[-1] == 0.0


def test_rsi_mid_on_alternating_series_and_bounded():
    close = pd.Series([10 + (i % 2) for i in range(60)], dtype=float)   # 10,11,10,11...
    v = indicators.rsi(close, 14).iloc[-1]
    assert 0 <= v <= 100
    assert 30 < v < 70                       # balanced up/down -> near 50


# ---- ATR + volatility-scaled stop ----------------------------------------
def _vol_df(n=30):
    close = [20.0 + (i % 2) * 4 for i in range(n)]                          # swings 20<->24
    df = pd.DataFrame({"High": [c + 3 for c in close], "Low": [c - 3 for c in close],
                       "Close": close, "Volume": [1_000_000] * n})
    df.index = pd.date_range("2026-01-01", periods=n)                       # aligned index
    return df


def test_atr_is_positive_on_volatile_series():
    assert indicators.atr(_vol_df(), 14).iloc[-1] > 0


def test_atr_stop_clamps_to_2x_flat_on_high_vol():
    df = _vol_df()
    price = float(df["Close"].iloc[-1])
    rules = {"defaults": {"stop_loss_pct": 5, "atr_stop_mult": 2.5, "atr_period": 14,
                          "take_profit_mode": "trailing", "trailing_stop_pct": 50,
                          "trend_break_fast": 20, "trend_break_slow": 50,
                          "trend_break_slow_level": "watch",
                          "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7}}}
    out = exits.evaluate_exit(df, {"ticker": "VOL", "entry_price": price / 0.85}, rules)
    stop = next((s for s in out["signals"] if s["type"] == "stop_loss"), None)
    assert stop is not None
    assert "stop -10%" in stop["detail"]     # ATR wanted ~70%, clamped to 2x the flat 5%


def test_atr_stop_off_by_default_keeps_flat_stop():
    df = _vol_df()
    price = float(df["Close"].iloc[-1])
    rules = {"defaults": {"stop_loss_pct": 5, "atr_stop_mult": 0,
                          "take_profit_mode": "trailing", "trailing_stop_pct": 50,
                          "trend_break_fast": 20, "trend_break_slow": 50,
                          "trend_break_slow_level": "watch",
                          "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7}}}
    out = exits.evaluate_exit(df, {"ticker": "VOL", "entry_price": price / 0.90}, rules)
    stop = next((s for s in out["signals"] if s["type"] == "stop_loss"), None)
    assert stop is not None and "stop -5%" in stop["detail"]
