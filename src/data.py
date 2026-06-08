from pathlib import Path
import pandas as pd

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


def validate(df, ticker: str, min_rows: int = 50):
    """Return (ok, reason). reason is '' when ok."""
    if df is None or len(df) == 0:
        return False, f"{ticker}: no data"
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return False, f"{ticker}: missing columns {missing}"
    if len(df) < min_rows:
        return False, f"{ticker}: only {len(df)} rows (need >= {min_rows})"
    if df["Close"].isna().all() or (df["Close"] <= 0).any():
        return False, f"{ticker}: invalid close prices"
    return True, ""


def cache_path(ticker: str, data_dir) -> Path:
    return Path(data_dir) / f"{ticker}.csv"


def save_cache(df, ticker: str, data_dir) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(ticker, data_dir))


def load_cache(ticker: str, data_dir):
    path = cache_path(ticker, data_dir)
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return None


def fetch_history(ticker: str, days: int):
    """Download daily OHLCV from yfinance. Network call — not used in tests."""
    import yfinance as yf

    period_days = int(days * 1.6) + 10  # buffer for weekends/holidays
    df = yf.download(
        ticker,
        period=f"{period_days}d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    # Newer yfinance returns MultiIndex columns even for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df
