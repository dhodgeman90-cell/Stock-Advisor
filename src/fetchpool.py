"""Run per-ticker network fetches in parallel.

The briefing enriches each shortlisted candidate with several independent network
lookups (analyst, insider, earnings, options, short interest, SEC filings, headlines).
Done sequentially that is dozens of serial round-trips; the calls are I/O-bound, so a
small thread pool collapses the wall-clock time into the slowest single call.

Each task is isolated: one ticker raising never sinks the others — the failure is
swallowed and that ticker maps to the supplied neutral default, preserving the
graceful-degradation guarantee the rest of the engine relies on.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

# ponytail: plain thread pool, fine for I/O-bound HTTP at watchlist scale (tens of
# tickers). Revisit (async / batching) only if we ever fan out to hundreds.
MAX_WORKERS = 8


def fetch_map(tickers, fn, *, default=None, max_workers=MAX_WORKERS,
              timeout=None, log=print) -> dict:
    """Return {ticker: fn(ticker)} computed in parallel.

    `fn` is called once per ticker. A failure OR a `timeout`-second overrun maps that
    ticker to `default` and emits a one-line notice via `log` (was silent before — a
    dropped ticker looked identical to a real no-opinion result). `timeout=None` waits
    indefinitely (the network-level timeout in data.fetch_history is the real hang guard;
    this is a secondary per-ticker bound). Pass `log=None` to silence. Order-independent.
    """
    tickers = list(dict.fromkeys(tickers))   # de-dupe, preserve first-seen order
    if not tickers:
        return {}
    out = {}
    workers = max(1, min(max_workers, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, t): t for t in tickers}
        for fut, ticker in futures.items():
            try:
                out[ticker] = fut.result(timeout=timeout)
            except FutureTimeout:
                out[ticker] = default() if callable(default) else default
                if log:
                    log(f"[fetchpool: {ticker} timed out after {timeout}s -> default]")
            except Exception as e:
                out[ticker] = default() if callable(default) else default
                if log:
                    log(f"[fetchpool: {ticker} failed -> default: {e}]")
    return out
