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
