import pandas as pd
from src import indicators


def _rsi_subscore(r: float) -> float:
    """RSI -> 0..1. Ideal band 50-70; overbought (>80) scores 0."""
    if pd.isna(r):
        return 0.0
    if r > 80:
        return 0.0
    if 50 <= r <= 70:
        return 1.0
    if r < 50:
        return max(0.0, (r - 30) / 20)   # 30->0, 50->1
    return max(0.0, 1 - (r - 70) / 10)   # 70->1, 80->0


def _breakout_subscore(ratio: float) -> float:
    """Within 10% of the rolling high scales 0..1."""
    return max(0.0, min(1.0, (ratio - 0.9) / 0.1))


def _volume_subscore(ratio: float) -> float:
    """2x average volume or more scores full marks."""
    return max(0.0, min(1.0, ratio / 2.0))


def compute_components(df: pd.DataFrame) -> dict:
    close = df["Close"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    sma20 = float(indicators.sma(close, 20).iloc[-1])
    sma50 = float(indicators.sma(close, 50).iloc[-1])
    rsi_val = float(indicators.rsi(close, 14).iloc[-1])

    trend = (0.5 if price > sma50 else 0.0) + (0.5 if sma20 > sma50 else 0.0)
    momentum = _rsi_subscore(rsi_val)
    breakout = _breakout_subscore(indicators.breakout_strength(close, 20))
    volume_s = _volume_subscore(indicators.volume_ratio(volume, 20))
    pullback = 1.0 if (price > sma50 and price < sma20) else 0.0

    return {
        "trend": trend,
        "momentum": momentum,
        "breakout": breakout,
        "volume": volume_s,
        "pullback": pullback,
    }


def score_ticker(df: pd.DataFrame, ticker: str, weights: dict, settings: dict) -> dict:
    min_price = settings.get("min_price", 5.0)
    # Liquidity gate is DOLLAR volume, not share count. A share-count floor wrongly excludes
    # high-priced names that are highly liquid in dollars — e.g. NVR trades ~28k shares/day but
    # at ~$8k/share that's ~$224M/day. Dollar volume is what actually bounds fill quality, and
    # it also lets a broader (small/mid-cap) universe be screened on one honest yardstick.
    min_dollar_volume = settings.get("min_dollar_volume", 10_000_000)

    price = float(df["Close"].iloc[-1])
    avg_dollar_vol = float((df["Close"] * df["Volume"]).rolling(20).mean().iloc[-1])

    if price < min_price:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": f"price ${price:.2f} below floor ${min_price:.2f}",
        }
    if pd.isna(avg_dollar_vol) or avg_dollar_vol < min_dollar_volume:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": f"avg $volume ${avg_dollar_vol:,.0f}/day below floor ${min_dollar_volume:,}",
        }

    components = compute_components(df)
    total_w = sum(weights.values())
    raw = sum(components[k] * weights.get(k, 0) for k in components)
    score = (100 * raw / total_w) if total_w else 0.0

    return {
        "ticker": ticker,
        "excluded": False,
        "score": score,
        "components": components,
    }


# ===================== Relative-strength entry model (Phase 3) ==============
# The legacy score puts 60% of its weight on breakout + volume, so it buys the 20-day high on
# a 2x-volume spike — then stops out on the pullback. The live scorecard shows the result: the
# highest-score band has the WORST forward alpha (the "inverted top band"). This entry model
# ranks names by cross-sectional relative strength vs SPY and prefers a CONSTRUCTIVE pullback in
# a strong name over a fresh-high chase. It's opt-in (settings["entry_model"]); compute_components
# and score_ticker are untouched, so the default path stays byte-for-byte identical.

def relative_strength(close, spy_close, lookback=63):
    """Trailing return of `close` minus SPY's over `lookback` bars, as a percent (as-of the last
    bar). Positive = outperforming the index. Reads only the last lookback+1 closes, so it never
    peeks ahead. 0.0 if either series is too short to measure."""
    if len(close) <= lookback or len(spy_close) <= lookback:
        return 0.0
    r_name = float(close.iloc[-1]) / float(close.iloc[-1 - lookback]) - 1.0
    r_spy = float(spy_close.iloc[-1]) / float(spy_close.iloc[-1 - lookback]) - 1.0
    return (r_name - r_spy) * 100.0


def cross_sectional_rank(rs_by_ticker):
    """Percentile rank (0..1) of each ticker's relative strength across the day's universe:
    strongest -> 1.0, weakest -> 0.0, ties share the average. Names with None RS are dropped; a
    lone eligible name gets 0.5 (nothing to rank it against)."""
    items = [(tk, v) for tk, v in rs_by_ticker.items() if v is not None]
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0][0]: 0.5}
    vals = [v for _, v in items]
    ranks = {}
    for tk, v in items:
        below = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        ranks[tk] = (below + (equal - 1) / 2.0) / (n - 1)
    return ranks


def constructive_pullback(df):
    """1.0 for a shallow, constructive pullback in an uptrend — price above a RISING 50-day MA
    but a few % below the 20-day MA (buying a dip in strength) — fading as the pullback deepens
    past ~15% or the name extends above the 20-day MA. 0 when there's no uptrend to buy (price
    at/below the 50-day MA, or the 50-day MA not rising). Deliberately gives NO credit for a
    fresh 20-day high (the breakout-chasing the top band inverts on)."""
    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = float(indicators.sma(close, 20).iloc[-1])
    sma50_series = indicators.sma(close, 50)
    sma50 = float(sma50_series.iloc[-1])
    sma50_prev = float(sma50_series.iloc[-6]) if len(close) > 55 else sma50
    if pd.isna(sma20) or pd.isna(sma50) or price <= sma50 or sma50 <= sma50_prev:
        return 0.0
    below = (sma20 - price) / sma20 * 100.0
    if below <= 0:
        return 0.3                            # above the 20-day = extended, not a dip
    if below <= 8:
        return 1.0                            # ideal shallow dip
    return max(0.0, 1 - (below - 8) / 7)       # 8% -> 1, fading to 0 by ~15%


def rs_entry_rank(df, rs_pct):
    """Entry-rank (0..100) for the relative-strength model: rewards cross-sectional relative
    strength (rs_pct in 0..1) plus a constructive pullback, trend, and momentum — and gives NO
    credit for chasing a fresh 20-day high on a volume spike. Reuses compute_components for the
    trend/momentum sub-scores."""
    c = compute_components(df)
    return 55.0 * rs_pct + 20.0 * c["trend"] + 15.0 * c["momentum"] + 10.0 * constructive_pullback(df)
