# Backtest Max-Drawdown Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a portfolio-level max-drawdown metric (strategy vs buy-and-hold) to the backtest report so the timing edge — smaller drawdowns — is visible alongside returns.

**Architecture:** Three new pure helpers in `src/backtest.py` — `max_drawdown` (worst peak-to-trough of an equity series), `strategy_equity_curve` and `buy_and_hold_equity_curve` (equal-weight daily portfolio curves built from the already-loaded histories + trades). `render_backtest_report` gains two lines; `run` wires the helpers through. No new data fetching, no new config knobs.

**Tech Stack:** Python 3.14, pandas, pytest. Run tests with `& .\.venv\Scripts\python.exe -m pytest`.

---

## File Structure

- **Modify:** `src/backtest.py` — add `import pandas as pd`; add `max_drawdown`, `_strategy_slice`, `_portfolio_curve`, `strategy_equity_curve`, `buy_and_hold_equity_curve`; extend `render_backtest_report` signature + body; wire into `run`.
- **Modify (tests):** `tests/test_backtest.py` — add tests for each new helper and the report lines. Reuses `tests/helpers.make_df` (daily `DatetimeIndex` from 2024-01-01, Open=High=Low=Close=price).

Conventions to match: negative percentages for drawdown; `:+.1f` formatting in the report; trades carry string `entry_date`/`exit_date` (e.g. `"2024-01-02"`) that match `str(df.index[i].date())`.

---

### Task 1: `max_drawdown` pure helper

**Files:**
- Modify: `src/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backtest.py`:

```python
def test_max_drawdown_flat_is_zero():
    assert backtest.max_drawdown([100.0, 100.0, 100.0]) == 0.0


def test_max_drawdown_monotonic_up_is_zero():
    assert backtest.max_drawdown([100.0, 110.0, 130.0]) == 0.0


def test_max_drawdown_simple_dip():
    # peak 100 -> trough 70 = -30%
    assert round(backtest.max_drawdown([100.0, 70.0, 90.0]), 1) == -30.0


def test_max_drawdown_picks_worst_after_recovery():
    # 100 -> 90 (-10%), recover to 120, drop to 84 (-30% off the new peak 120)
    assert round(backtest.max_drawdown([100.0, 90.0, 120.0, 84.0]), 1) == -30.0


def test_max_drawdown_empty_is_zero():
    assert backtest.max_drawdown([]) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -k max_drawdown -v`
Expected: FAIL with `AttributeError: module 'src.backtest' has no attribute 'max_drawdown'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/backtest.py` (after the imports add `import pandas as pd` at the top of the file; place the function near the other summary helpers, e.g. after `compounded_per_name`):

```python
def max_drawdown(values) -> float:
    """Worst peak-to-trough drop of an equity series, as a negative percent.

    0.0 if the series never falls below a running peak (or is empty).
    """
    peak = None
    worst = 0.0
    for v in values:
        v = float(v)
        if peak is None or v > peak:
            peak = v
        if peak:
            dd = (v - peak) / peak * 100
            if dd < worst:
                worst = dd
    return worst
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -k max_drawdown -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): add max_drawdown helper"
```

---

### Task 2: Equity curves (strategy + buy-and-hold)

**Files:**
- Modify: `src/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backtest.py`:

```python
def test_strategy_equity_curve_tracks_trade_then_flat_in_cash():
    # Hold from 01-02 to 01-04 (+20%), then sit in cash flat at 1.20.
    df = make_df([100.0, 100.0, 110.0, 120.0, 120.0, 120.0])
    trades = [{"ticker": "T", "entry_date": "2024-01-02", "exit_date": "2024-01-04",
               "entry_price": 100.0, "exit_price": 120.0, "return_pct": 20.0,
               "hold_days": 2, "reason": "take_profit"}]
    curve = backtest.strategy_equity_curve({"T": df}, trades)
    assert [round(v, 3) for v in curve] == [1.0, 1.0, 1.1, 1.2, 1.2, 1.2]


def test_strategy_equity_curve_averages_equal_weight_across_tickers():
    a = make_df([100.0, 100.0, 120.0])           # A trades +20% over the window
    b = make_df([100.0, 100.0, 100.0])           # B never trades -> flat at 1.0
    trades = [{"ticker": "A", "entry_date": "2024-01-01", "exit_date": "2024-01-03",
               "entry_price": 100.0, "exit_price": 120.0, "return_pct": 20.0,
               "hold_days": 2, "reason": "take_profit"}]
    curve = backtest.strategy_equity_curve({"A": a, "B": b}, trades)
    # A slice [1.0, 1.0, 1.2]; B slice [1.0, 1.0, 1.0]; mean [1.0, 1.0, 1.1]
    assert [round(v, 3) for v in curve] == [1.0, 1.0, 1.1]


def test_strategy_equity_curve_empty_histories():
    assert backtest.strategy_equity_curve({}, []) == []


def test_buy_and_hold_equity_curve_equal_weight():
    a = make_df([100.0, 110.0, 120.0])           # normalized [1.0, 1.1, 1.2]
    b = make_df([100.0, 100.0, 80.0])            # normalized [1.0, 1.0, 0.8]
    curve = backtest.buy_and_hold_equity_curve({"A": a, "B": b})
    assert [round(v, 3) for v in curve] == [1.0, 1.05, 1.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -k equity_curve -v`
Expected: FAIL with `AttributeError: module 'src.backtest' has no attribute 'strategy_equity_curve'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/backtest.py` (after `buy_and_hold`):

```python
def _portfolio_curve(slices) -> list:
    """Equal-weight mean of normalized per-ticker slice Series.

    Aligns on the union of their dates and forward-fills, so a name with a
    shorter history contributes only once it has data (leading gaps are NaN and
    excluded from the mean). Returns the daily portfolio values.
    """
    if not slices:
        return []
    frame = pd.concat(slices, axis=1).sort_index().ffill()
    return [float(v) for v in frame.mean(axis=1, skipna=True).tolist()]


def _strategy_slice(df, ticker_trades):
    """Normalized account value for one ticker over its history (starts at 1.0).

    Flat while in cash; tracks close/entry_price while holding; locks in the
    realized (cost-inclusive) factor on the trade's exit date, then flat again.
    """
    by_entry = {t["entry_date"]: t for t in ticker_trades}
    factor = 1.0
    entry_price = None
    open_trade = None
    out = []
    for ts, close in zip(df.index, df["Close"]):
        d = str(ts.date())
        if open_trade is None and d in by_entry:
            open_trade = by_entry[d]
            entry_price = open_trade["entry_price"]
        if open_trade is not None:
            if d == open_trade["exit_date"]:
                factor = factor * (1 + open_trade["return_pct"] / 100)
                out.append(factor)
                open_trade = None
                entry_price = None
            else:
                out.append(factor * (float(close) / entry_price))
        else:
            out.append(factor)
    return pd.Series(out, index=df.index)


def strategy_equity_curve(histories, trades) -> list:
    """Equal-weight daily portfolio curve for the strategy (cash between trades)."""
    by_ticker = {}
    for t in trades:
        by_ticker.setdefault(t["ticker"], []).append(t)
    slices = [_strategy_slice(df, by_ticker.get(ticker, []))
              for ticker, df in histories.items()]
    return _portfolio_curve(slices)


def buy_and_hold_equity_curve(histories) -> list:
    """Equal-weight daily portfolio curve for always-invested buy-and-hold."""
    slices = []
    for df in histories.values():
        first = float(df["Close"].iloc[0])
        if first:
            slices.append(df["Close"].astype(float) / first)
    return _portfolio_curve(slices)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -k equity_curve -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): equal-weight strategy and buy-and-hold equity curves"
```

---

### Task 3: Report the two drawdown lines

**Files:**
- Modify: `src/backtest.py` (`render_backtest_report`)
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backtest.py`:

```python
def test_report_includes_max_drawdown_lines():
    trades = [{"ticker": "AAA", "entry_date": "2024-01-01", "exit_date": "2024-01-05",
               "entry_price": 100.0, "exit_price": 108.0, "return_pct": 8.0,
               "hold_days": 4, "reason": "take_profit"}]
    summary = backtest.summarize(trades)
    text = backtest.render_backtest_report(summary, 5.0, trades, "2026-06-08",
                                           strategy_dd=-9.0, buyhold_dd=-28.0)
    assert "Strategy max drawdown: **-9.0%**" in text
    assert "Buy-and-hold max drawdown: **-28.0%**" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_report_includes_max_drawdown_lines -v`
Expected: FAIL — `render_backtest_report() got an unexpected keyword argument 'strategy_dd'`

- [ ] **Step 3: Write minimal implementation**

In `src/backtest.py`, change the `render_backtest_report` signature from:

```python
def render_backtest_report(summary, baseline, trades, date_str, label="default", sources=None) -> str:
```

to:

```python
def render_backtest_report(summary, baseline, trades, date_str, label="default",
                           sources=None, strategy_dd=0.0, buyhold_dd=0.0) -> str:
```

Then, in the same function, find this block:

```python
        "### Strategy vs buy-and-hold (per name, comparable)",
        f"- Strategy return per name (compounded): **{compounded:+.1f}%**",
        f"- Buy-and-hold baseline (avg per watchlist name): **{baseline:+.1f}%**",
        f"- Avg return per trade: **{summary['avg_trade_return']:+.1f}%**",
```

and replace it with (adds the two drawdown lines):

```python
        "### Strategy vs buy-and-hold (per name, comparable)",
        f"- Strategy return per name (compounded): **{compounded:+.1f}%**",
        f"- Buy-and-hold baseline (avg per watchlist name): **{baseline:+.1f}%**",
        f"- Avg return per trade: **{summary['avg_trade_return']:+.1f}%**",
        f"- Strategy max drawdown: **{strategy_dd:+.1f}%**",
        f"- Buy-and-hold max drawdown: **{buyhold_dd:+.1f}%**",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -v`
Expected: PASS — the new test passes and all existing `render_backtest_report` tests still pass (the new params default to 0.0).

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): report strategy and buy-and-hold max drawdown"
```

---

### Task 4: Wire into `run` and verify end-to-end

**Files:**
- Modify: `src/backtest.py` (`run`)

- [ ] **Step 1: Wire the helpers into `run`**

In `src/backtest.py`, find this block in `run`:

```python
    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str,
                                  label=label, sources=sources)
```

and replace it with:

```python
    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    strategy_dd = max_drawdown(strategy_equity_curve(histories, all_trades))
    buyhold_dd = max_drawdown(buy_and_hold_equity_curve(histories))
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str,
                                  label=label, sources=sources,
                                  strategy_dd=strategy_dd, buyhold_dd=buyhold_dd)
```

- [ ] **Step 2: Run the full test suite**

Run: `& .\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS — all prior tests plus the 10 new ones (was 80; expect ~90).

- [ ] **Step 3: Run the backtest end-to-end and eyeball the report**

Run: `& .\.venv\Scripts\python.exe -m src.backtest`
Expected: prints the report and writes `reports/backtest-default-<today>.md`. Confirm the "Strategy vs buy-and-hold" section now shows two new lines:
`- Strategy max drawdown: **-X.X%**` and `- Buy-and-hold max drawdown: **-Y.Y%**`, both negative (or `+0.0%` if no drop), and the strategy drawdown is no deeper than buy-and-hold's. (If offline, tickers may be served from cache — the lines should still render.)

- [ ] **Step 4: Commit**

```bash
git add src/backtest.py
git commit -m "feat(backtest): wire max drawdown into the run report"
```

---

## Notes for the implementer

- **Why the strategy curve uses `return_pct` at exit:** `return_pct` already includes the round-trip transaction cost (from `_net_return`), so locking in `factor *= (1 + return_pct/100)` on the exit date keeps the equity curve consistent with the per-trade table. Intermediate hold days use the raw `close/entry_price` mark (cost is only realized at exit). Do not re-apply cost in the curve.
- **Dates are strings:** trades store `entry_date`/`exit_date` as `str(date)` (e.g. `"2024-01-02"`), matched against `str(ts.date())` per row. Keep that exact comparison — don't reformat.
- **Drawdown sign:** `max_drawdown` returns a negative percent (0.0 when flat). The report uses `:+.1f`, so `-9.0` renders as `-9.0%` and `0.0` as `+0.0%`.
- **No new config:** these are computed from data already loaded in `run`; there are no new `exits.yaml`/watchlist knobs this iteration (per the spec's YAGNI scope).
