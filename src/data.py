import datetime as dt
from pathlib import Path
import pandas as pd

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]
WARMUP_DAYS = 100   # extra calendar days so the SMA-50 / MIN_HISTORY ramp is warm


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


def _window_bounds(days, today=None, warmup=WARMUP_DAYS):
    """Return (start_iso, end_iso) for an explicit yfinance date range.

    end is exclusive (yfinance convention) so we add one day to include today.
    """
    today = today or dt.date.today()
    start = today - dt.timedelta(days=int(days) + int(warmup))
    end = today + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def fetch_history(ticker: str, days: int):
    """Download daily OHLCV from yfinance over an explicit date window.

    Network call — not used in tests. The window is days + WARMUP_DAYS calendar
    days so the requested `days` span is fully usable after indicator warm-up.
    """
    import yfinance as yf

    start, end = _window_bounds(days)
    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    # Newer yfinance returns MultiIndex columns even for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df
