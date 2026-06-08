# Backtest Max-Drawdown Metric — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)
**Area:** `src/backtest.py`, tests

## Problem

The backtest report compares strategy return to buy-and-hold per name. Over the
current ~2-year straight-up window the strategy trails buy-and-hold (+49% vs
+96%), which is expected — a timing system's real edge is **smaller drawdowns in
flat/down markets**, not bigger returns in a rip-roaring bull market. The report
currently has no way to show that edge. We need a **max-drawdown** metric so the
strategy's risk profile is visible alongside its return.

## Goal

Add max drawdown for both the strategy and the buy-and-hold baseline to the
backtest report, as one honest, directly-comparable pair of numbers
(e.g. "Strategy −9% vs buy-and-hold −28%").

Non-goals (YAGNI for this iteration): drawdown dates, recovery time, risk-free
interest on idle cash, any new config knobs.

## Decisions (from brainstorming)

1. **Level: portfolio, equal-weight.** Measure drawdown on one daily equity curve
   for the whole watchlist (each name an equal slice), not by averaging per-name
   drawdowns. Per-name averaging hides correlation (names crash together) and
   understates real account drawdown. Portfolio-level is the standard, defensible
   metric — important if the track record is ever shared — and is apples-to-apples
   with the existing equal-weight buy-and-hold baseline.
2. **Idle cash is flat (0% return).** When the strategy is not holding a given
   name, that name's slice holds its value flat until the next trade. Conservative
   and honest; drawdown can only occur while invested, so cash periods are exactly
   what protect the strategy — which is the edge we want to show. No risk-free rate.
3. **Costs:** round-trip transaction cost applied once at trade exit, consistent
   with `_net_return` (`cost_pct_per_side`), so the equity curve and the per-trade
   returns cannot disagree.

## Design

### 1. `max_drawdown(series) -> float` (new pure helper)

Takes an iterable of equity values (the daily curve). Returns the worst
`(value − running_peak) / running_peak`, as a **negative percentage** (0.0 if the
curve never drops). Pure and trivially unit-testable.

### 2. `equity_curve(histories, trades, rules) -> list[float]` (new helper)

Builds the strategy's daily equal-weight portfolio equity curve.

- Establish a **common date index** = the union of all tickers' dates, sorted.
- For each ticker, build a daily **slice** series, normalized to start at 1.0:
  - Flat at its current compounded value while in cash.
  - While in a trade (entry_date → exit_date), the slice tracks
    `price / entry_price` relative to the running compounded value.
  - At exit, lock in the realized factor with the round-trip cost applied
    (same cost as `_net_return`); the slice then stays flat until the next trade.
  - Forward-fill across the common date index; a slice only contributes on days
    the ticker actually has data (a late-listing name does not distort earlier days).
- Portfolio value each day = **mean of the slices present that day**.
- Returns the portfolio value series.

A buy-and-hold curve is the same construction with every slice always invested
(the normalized close series) — implemented either by reusing `equity_curve` with
a synthetic always-open trade per ticker, or a small sibling helper, whichever is
cleaner at implementation time. Both reduce to: equal-weight mean of normalized
per-ticker series → `max_drawdown`.

### 3. `render_backtest_report` (extend)

Add two lines to the existing "Strategy vs buy-and-hold (per name, comparable)"
section:

```
- Strategy max drawdown: **−X.X%**
- Buy-and-hold max drawdown: **−Y.Y%**
```

Signature gains the two drawdown values (or a small dict) as parameters.

### 4. `run` (wire through)

`run` already has `histories` and `all_trades`. Compute the strategy curve and the
buy-and-hold curve from those, derive the two drawdowns via `max_drawdown`, and
pass them into `render_backtest_report`. No new data fetching.

## Edge cases

- **No trades:** strategy curve is flat → drawdown 0.0% (reported, not an error).
- **Empty `histories`** (all tickers skipped/offline): both drawdowns 0.0%,
  consistent with how `buy_and_hold` already degrades.
- **Mismatched date ranges:** align on the union of dates, forward-fill each slice;
  a slice contributes only on days it has data.

## Testing (TDD, matching the existing pytest suite)

- `max_drawdown`: flat → 0; monotonic up → 0; known −30% dip → −30%;
  recovery-then-deeper-dip picks the worst.
- `equity_curve`: a single hand-built trade reproduces the expected slice;
  a cash gap stays flat; two tickers average correctly.
- Report: snapshot-style check that the two new lines render with the correct
  sign and one-decimal rounding.

## Out of scope

Drawdown start/end dates, recovery duration, risk-free cash yield, new config
knobs. Revisit only if a real track record justifies richer reporting.
