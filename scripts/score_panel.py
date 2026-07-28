"""Vectorized panel version of scoring.score_ticker, for 574 names x 7 years.

The per-ticker loop in src/scoring.py is far too slow for a 200k-observation study, so this
recomputes the SAME formula across the whole price panel at once. verify() checks it against
the real scoring.score_ticker on random (ticker, date) pairs — if that check ever fails, the
study is measuring a different model than the app runs and its results are meaningless.
"""
import glob
import os

import numpy as np
import pandas as pd

WEIGHTS = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 10_000_000


def load_panel(data_dir="data", min_bars=800):
    close, volume = {}, {}
    for f in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        t = os.path.basename(f)[:-4]
        try:
            d = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(d) < min_bars:
            continue
        d.columns = [c.capitalize() for c in d.columns]
        if "Close" not in d or "Volume" not in d:
            continue
        close[t], volume[t] = d["Close"].astype(float), d["Volume"].astype(float)
    C = pd.DataFrame(close).sort_index()
    V = pd.DataFrame(volume).sort_index()
    return C, V


def _rsi(C, n=14):
    d = C.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    # scoring.py uses indicators.rsi -> Wilder smoothing via ewm(alpha=1/n, adjust=False)
    ru = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = ru / rd.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(rd != 0, 100.0)


def _rsi_sub(r):
    s = pd.DataFrame(np.nan, index=r.index, columns=r.columns)
    s = s.mask(r < 50, ((r - 30) / 20).clip(lower=0.0))
    s = s.mask((r >= 50) & (r <= 70), 1.0)
    s = s.mask((r > 70) & (r <= 80), (1 - (r - 70) / 10).clip(lower=0.0))
    s = s.mask(r > 80, 0.0)
    return s.fillna(0.0)


def panel_scores(C, V):
    """Composite 0-100 score per (date, ticker); NaN where the price/liquidity gate excludes."""
    sma20, sma50 = C.rolling(20).mean(), C.rolling(50).mean()
    trend = (C > sma50).astype(float) * 0.5 + (sma20 > sma50).astype(float) * 0.5
    momentum = _rsi_sub(_rsi(C))
    breakout = ((C / C.rolling(20).max() - 0.9) / 0.1).clip(0.0, 1.0)
    volume = (V / V.rolling(20).mean() / 2.0).clip(0.0, 1.0)
    pullback = ((C > sma50) & (C < sma20)).astype(float)

    raw = (breakout * WEIGHTS["breakout"] + volume * WEIGHTS["volume"]
           + momentum * WEIGHTS["momentum"] + trend * WEIGHTS["trend"]
           + pullback * WEIGHTS["pullback"])
    score = 100 * raw / sum(WEIGHTS.values())

    adv = (C * V).rolling(20).mean()
    eligible = (C >= MIN_PRICE) & (adv >= MIN_DOLLAR_VOL) & sma50.notna() & momentum.notna()
    return score.where(eligible)


def verify(C, V, scores, n=40, seed=0):
    """Assert the panel matches src.scoring.score_ticker on random (ticker, date) pairs."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import scoring

    rng = np.random.default_rng(seed)
    checked = mismatch = 0
    settings = {"min_price": MIN_PRICE, "min_dollar_volume": MIN_DOLLAR_VOL}
    tickers = list(C.columns)
    for _ in range(n * 4):
        if checked >= n:
            break
        t = tickers[rng.integers(len(tickers))]
        i = int(rng.integers(200, len(C) - 1))
        date = C.index[i]
        if pd.isna(C.at[date, t]):
            continue
        df = pd.DataFrame({"Close": C[t].iloc[: i + 1], "Volume": V[t].iloc[: i + 1]}).dropna()
        if len(df) < 60:
            continue
        r = scoring.score_ticker(df, t, WEIGHTS, settings)
        panel = scores.at[date, t]
        if r.get("excluded"):
            if pd.notna(panel):
                mismatch += 1
                print(f"  MISMATCH {t} {date.date()}: real=excluded panel={panel:.3f}")
        else:
            if pd.isna(panel) or abs(panel - r["score"]) > 0.02:
                mismatch += 1
                print(f"  MISMATCH {t} {date.date()}: real={r['score']:.3f} panel={panel}")
        checked += 1
    print(f"verified {checked} random (ticker, date) pairs -> {mismatch} mismatches")
    return mismatch == 0
