"""Pull ~7 years of daily history for the full scan universe.

Prerequisite for any real validation: every non-watchlist cache currently holds exactly
206 bars (lookback_days 200 + warmup), which is why no backtest in the repo can measure
the strategy that actually runs. data/ is gitignored, so this only grows the local cache.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import config, data, profile as P  # noqa: E402

YEARS = 7
DAYS = int(YEARS * 365)

prof = P.Profile.for_repo()
data_dir = prof.data_dir

universe = sorted(
    {t for t in (config.load_universe(prof.config_dir) or [])}
    | set(config.load_watchlist(prof.config_dir)["tickers"])
    | {"SPY", "QQQ", "IWM"}          # index refs for regime + relative strength
)
print(f"universe: {len(universe)} tickers, requesting ~{YEARS}y of daily bars", flush=True)

t0 = time.time()
batch = data.fetch_history_batch(universe, DAYS)
print(f"download finished in {time.time() - t0:.0f}s", flush=True)

saved = skipped = 0
depths = []
for ticker in universe:
    df = batch.get(ticker)
    ok, _ = data.validate(df, ticker) if df is not None else (False, "no data")
    if ok:
        data.save_cache(df, ticker, data_dir)
        depths.append(len(df))
        saved += 1
    else:
        skipped += 1

depths.sort()
print(f"saved {saved}, skipped {skipped}", flush=True)
if depths:
    print(f"bars per ticker: min {depths[0]}  p10 {depths[len(depths)//10]}  "
          f"median {depths[len(depths)//2]}  max {depths[-1]}", flush=True)
    print(f"tickers with >= 1000 bars (~4y): {sum(1 for d in depths if d >= 1000)}", flush=True)
