import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100) with Wilder's smoothing (RMA) — the standard used by
    TradingView/StockCharts/etc. The old simple-rolling-mean version diverged from every
    charting platform. On our 200-bar lookback the ewm(adjust=False) recursion converges to
    Wilder's seed long before the latest bar, which is the only value we read."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder). Volatility in price units, for volatility-scaled stops."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def breakout_strength(close: pd.Series, window: int = 20) -> float:
    """Latest close as a fraction of its rolling-max high (1.0 = at/above high)."""
    recent_high = close.rolling(window).max().iloc[-1]
    latest = close.iloc[-1]
    if pd.isna(recent_high) or recent_high == 0:
        return 0.0
    return float(latest / recent_high)


def volume_ratio(volume: pd.Series, window: int = 20) -> float:
    """Latest volume divided by its rolling average (2.0 = twice normal)."""
    avg = volume.rolling(window).mean().iloc[-1]
    latest = volume.iloc[-1]
    if pd.isna(avg) or avg == 0:
        return 0.0
    return float(latest / avg)
