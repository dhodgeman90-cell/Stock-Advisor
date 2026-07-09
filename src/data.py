import datetime as dt
from pathlib import Path
import pandas as pd

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]
OHLC_COLS = ["Open", "High", "Low", "Close"]
WARMUP_DAYS = 100   # extra calendar days so the SMA-50 / MIN_HISTORY ramp is warm
DATA_TIMEOUT = 20   # seconds; cap a hung yfinance socket instead of blocking a worker forever


def _drop_incomplete(df):
    """Drop rows missing any OHLC value.

    yfinance intermittently returns a placeholder bar for the latest day that carries
    volume but NaN prices (it varies ticker-to-ticker on any given morning). Such a bar
    can never produce a valid price, yet it would otherwise become close.iloc[-1] and
    surface as "price unavailable" + a silent "hold". Stripping these rows here means a
    poisoned bar can never reach the engine — whether it arrives fresh from the network
    or from a previously-cached CSV.
    """
    if df is None or len(df) == 0:
        return df
    present = [c for c in OHLC_COLS if c in df.columns]
    if not present:
        return df
    return df.dropna(subset=present)


def validate(df, ticker: str, min_rows: int = 50):
    """Return (ok, reason). reason is '' when ok."""
    if df is None or len(df) == 0:
        return False, f"{ticker}: no data"
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return False, f"{ticker}: missing columns {missing}"
    if len(df) < min_rows:
        return False, f"{ticker}: only {len(df)} rows (need >= {min_rows})"
    close = df["Close"]
    # Backstop against a NaN trailing bar slipping through: the LAST close is what the
    # engine reads as "current price", so a NaN there must fail validation, not just an
    # all-NaN column. dropna() on the <= 0 check keeps NaN from masking a real zero/neg.
    if close.isna().all() or pd.isna(close.iloc[-1]) or (close.dropna() <= 0).any():
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
        return _drop_incomplete(pd.read_csv(path, index_col=0, parse_dates=True))
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
        timeout=DATA_TIMEOUT,
    )
    # Newer yfinance returns MultiIndex columns even for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return _drop_incomplete(df)


def _extract_ticker_frame(raw, ticker: str, chunk_len: int):
    """Pull one ticker's OHLCV frame out of a bulk yf.download(group_by='ticker') result."""
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker in set(raw.columns.get_level_values(0)):
            return _drop_incomplete(raw[ticker].copy())
        # some yfinance versions put the OHLC field at level 0 and the ticker at level -1
        if ticker in set(raw.columns.get_level_values(-1)):
            return _drop_incomplete(raw.xs(ticker, axis=1, level=-1).copy())
        return None
    # flat columns == a single-ticker chunk
    return _drop_incomplete(raw.copy()) if chunk_len == 1 else None


def fetch_history_batch(tickers, days: int, chunk_size: int = 60) -> dict:
    """Bulk daily OHLCV for a wide universe -> {ticker: df or None}. Network call.

    Chunked so a single bad symbol or a transient rate-limit only affects its chunk, which
    then degrades to one-at-a-time fetches. This is the two-stage funnel's stage-1 input:
    score every name cheaply from these frames, then enrich only the shortlist. Far fewer
    round-trips than looping fetch_history over hundreds of tickers.
    """
    import yfinance as yf

    start, end = _window_bounds(days)
    tickers = list(dict.fromkeys(str(t).upper() for t in tickers))
    out = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            raw = yf.download(chunk, start=start, end=end, interval="1d", auto_adjust=True,
                              progress=False, threads=True, group_by="ticker",
                              timeout=DATA_TIMEOUT)
        except Exception:
            raw = None
        if raw is None or len(raw) == 0:
            for t in chunk:                       # whole chunk failed -> try each once
                try:
                    out[t] = fetch_history(t, days)
                except Exception:
                    out[t] = None
            continue
        for t in chunk:
            out[t] = _extract_ticker_frame(raw, t, len(chunk))
    return out
