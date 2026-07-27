"""Date-window helpers for per-regime backtest slicing (pure, no network).

A stop/timing strategy can only be judged honestly across regimes — a bull run
flatters it, a selloff exposes it. These windows let the backtest report the same
strategy separately over the 2022 selloff, the 2023-24 bull, the recent stretch,
and the full cycle.
"""

# (start, end) as ISO date strings; None = open-ended on that side.
SUBPERIODS = {
    "2022_selloff": ("2022-01-01", "2022-12-31"),
    "2023_24_bull": ("2023-01-01", "2024-12-31"),
    "2025_26": ("2025-01-01", None),
    "full": (None, None),
}


def slice_histories(histories, start, end, *, min_rows=None):
    """Return {ticker: df.loc[start:end]} keeping only frames with >= min_rows rows.

    Does not mutate the input frames. start/end are ISO date strings or None
    (open-ended). A ticker whose in-window history is too short to score is dropped,
    so a regime never inherits a name that can't actually be traded in it.

    min_rows defaults to backtest.MIN_HISTORY (imported lazily to avoid a module
    import cycle, since backtest.per_regime_summary calls this).
    """
    if min_rows is None:
        from src.backtest import MIN_HISTORY
        min_rows = MIN_HISTORY
    out = {}
    for ticker, df in histories.items():
        sliced = df.loc[start:end]
        if len(sliced) >= min_rows:
            out[ticker] = sliced
    return out
