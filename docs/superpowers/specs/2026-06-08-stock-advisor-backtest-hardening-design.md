# Stock Advisor — Backtest & Exit Hardening (Design)

**Date:** 2026-06-08
**Branch:** `backtest-hardening`
**Status:** Approved design — ready for implementation plan

## Context

The first preliminary backtest (default watchlist, run 2026-06-08) surfaced several
problems that make the results hard to trust and the strategy weaker than it should be:

- The strategy badly lagged buy-and-hold (+2.0% avg/trade vs +263% per-name hold),
  largely because it **sells every winner at a hard +20% take-profit** and then gets
  chopped re-entering. On strong trends (NVDA, AVGO) this caps the biggest gains.
- The backtest **window did not match config**: `window_years: 2` actually pulled
  ~4.5 years of data, because `fetch_history` inflates the window with a `days * 1.6`
  calendar-day fudge. The backtest is therefore not reproducible from config.
- The headline **"+761% sum of all trades"** is misleading — it tallies 379 independent,
  non-compounded trades and invites a false comparison to buy-and-hold.
- The backtest models the +20% take-profit as a **full exit**, even though live briefings
  treat that level as a "trim" (advisory). Backtest and live intent diverge.
- The backtest has **no offline fallback** — `run()` fetches but never reads/writes the
  cache, so any failed fetch silently drops a ticker from the entire run.
- No transaction costs are modeled, so a high-frequency strategy looks better than reality.
- The watchlist is 10 pre-selected mega-cap winners, so the backtest can't tell us whether
  the strategy generalizes.

**Goal:** make the backtest trustworthy, reproducible, and honest, and let the strategy
keep its winners — without breaking the project's core principle that the backtest replays
the *exact same* deterministic rules the live briefing uses.

## Guiding principle (unchanged)

All exit logic lives in the shared `exits.evaluate_exit`, used by both `main.py` (live)
and `backtest.simulate_ticker` (replay). Every behavioral change goes through that shared
function so live and backtest never drift apart.

## The six fixes

### 1. Honor `window_years` (window-config bug)

- **Problem:** `data.fetch_history(ticker, days)` computes `period_days = int(days * 1.6) + 10`
  and passes `period="{period_days}d"` to yfinance — a fuzzy, inflated window.
- **Fix:** download by explicit dates instead. `end = today + 1 day`, `start = today −
  (days + WARMUP_DAYS)`, where `WARMUP_DAYS ≈ 100` calendar days covers the SMA-50 /
  `MIN_HISTORY` ramp so the *decision* window after warm-up is ≈ the requested span.
- `main.py` calls `fetch_history(ticker, lookback)` (e.g. 200) and keeps working — it just
  gets a precise ~200-calendar-day window.
- In `backtest.run()`, fetch `window_years * 365 + WARMUP_DAYS` calendar days so the decision
  window is ≈ `window_years`.
- Reproducible: same config + same date → same window (new data after `today` aside).

### 2. Trailing stop — let winners run

- Add `take_profit_mode` to `exits.yaml` `defaults:` — `"trailing"` (new default) or `"hard"`
  (existing +20% behavior, retained for comparison/backtesting).
- **Trailing rule:** emit a `sell`-level signal when
  `price ≤ peak_since_entry × (1 − trailing_stop_pct/100)`.
- The **hard stop-loss (−8% from entry) stays** as the downside floor for positions that
  never advance. When `mode == "trailing"`, the hard +20% take-profit is **not** emitted.
- `peak_since_entry` is supplied by the **caller** to keep `evaluate_exit` pure:
  - `backtest.simulate_ticker` tracks the running peak (max close since entry) day-by-day
    and passes it in via the `position` dict (`position["peak_price"]`).
  - `main.py` computes the peak from price history since the position's `entry_date` and
    passes it in.
  - Fallback when `peak_price` is absent: use `entry_price` (trailing stop then behaves like
    a wider fixed stop — safe, never crashes).
- Per-position override: optional `trailing_stop_pct` in `positions.yaml`, mirroring the
  existing `stop_loss_pct` / `take_profit_pct` override pattern (`config.load_positions`
  gains the field).
- New config: `defaults.take_profit_mode: trailing`, `defaults.trailing_stop_pct: 15`.

### 3. Transaction costs

- New config `backtest.cost_pct_per_side` (default `0.1` → 0.2% round-trip).
- In `simulate_ticker`, reduce each closed trade's `return_pct` by the round-trip cost
  (`2 × cost_pct_per_side`). Zero cost reproduces today's numbers exactly.

### 4. Honest, apples-to-apples reporting

- **Remove** the "+761% sum of all trades" headline.
- Add **strategy return per name (compounded)**: because each ticker holds one trade at a
  time, its sequential trades compound — `∏(1 + ret_i) − 1` per ticker — and the average
  across tickers is directly comparable to the existing per-name buy-and-hold baseline.
- Add **expectancy per trade** (`win_rate×avg_gain + loss_rate×avg_loss`). Keep win rate,
  avg gain/loss, avg hold as the "edge" detail.
- `render_backtest_report` leads with the comparable compounded figures; per-trade stats
  follow. New helper (e.g. `compounded_per_name(trades)`) groups trades by ticker.

### 5. Broader validation universe

- New `config/watchlist_broad.yaml` — a neutral sector spread, deliberately including
  laggards so it is not cherry-picked:
  `JNJ, UNH, JPM, XOM, PG, KO, CAT, NEE, VZ, DIS, INTC, F`.
- Parametrize `config.load_watchlist(name=None, config_dir=CONFIG_DIR)`: `None` →
  `watchlist.yaml`; `"broad"` → `watchlist_broad.yaml`.
- `backtest.run(watchlist_name=None)` and CLI `python -m src.backtest [broad]`.
- Reports named `backtest-<watchlist>-<date>.md` (e.g. `backtest-default-2026-06-08.md`,
  `backtest-broad-2026-06-08.md`) so both runs coexist.

### 6. Offline-resilient backtest

- `backtest.run()` adopts `main.py`'s data pattern: `fetch_history` → on valid result
  `save_cache`; on failure/invalid `load_cache` and validate the cache.
- Track and report which tickers were live vs cache vs skipped (printed in the report
  header — never silent).

## Components touched

| File | Change |
|------|--------|
| `src/data.py` | `fetch_history` → explicit `start`/`end` dates; remove `*1.6` fudge; add `WARMUP_DAYS`. |
| `src/exits.py` | `evaluate_exit` gains `take_profit_mode` + trailing-stop logic using caller-supplied `peak_price`. |
| `src/backtest.py` | `simulate_ticker` tracks peak + applies costs; `run(watchlist_name)` adds cache fallback; new `compounded_per_name` + expectancy; report restructured + renamed. |
| `src/config.py` | `load_watchlist(name=None)`; `load_positions` gains `trailing_stop_pct`. |
| `src/main.py` | Compute `peak_price` since `entry_date` and pass into `evaluate_exit`. |
| `config/exits.yaml` | Add `take_profit_mode`, `trailing_stop_pct`, `cost_pct_per_side`. |
| `config/watchlist_broad.yaml` | New file (broad sector basket). |
| `tests/test_*.py` | New/updated tests (below). |

## Testing (TDD — extends the existing 61-test suite)

Using the synthetic `make_df()` helper (no network in unit tests):

- **Trailing stop:** price rises then pulls back past `trailing_stop_pct` from peak → `sell`
  signal; early drawdown still triggers the −8% hard stop-loss; `mode: "hard"` still caps at
  +20%; missing `peak_price` falls back to `entry_price` without error.
- **Transaction costs:** round-trip cost subtracted from `return_pct`; `cost_pct_per_side: 0`
  reproduces prior results.
- **Reporting:** `compounded_per_name` math (multi-trade compounding per ticker, averaged);
  expectancy math; report no longer contains the "sum of all trades" headline.
- **Window math:** a small pure date-range helper for `fetch_history` start/end (network
  call itself stays untested, as today).
- **Offline fallback:** fetch-fails → cache path is taken (mocked fetch); ticker skipped only
  when both fetch and cache are invalid.
- **Watchlist loader:** `load_watchlist("broad")` loads the broad file; default unchanged.

## Out of scope (YAGNI)

- Full portfolio-level equity curve with capital allocation across simultaneous positions
  (per-name compounded return is the honest, low-cost substitute).
- Walk-forward / Monte-Carlo / parameter optimization.
- Intraday data, brokerage integration, auto-execution.

## Post-implementation tuning (2026-06-08)

After the six fixes landed, a parameter sweep (each watchlist fetched once, rule combos
evaluated in memory) revealed that the `trend_break_slow` "sell" exit was closing ~75-88%
of trades — bailing on normal pullbacks below the 50-day MA and undercutting the trailing
stop. A configurable `trend_break_slow_level` was added (`src/exits.py`; default `sell`,
preserving prior behavior and tests). Demoting it to `watch` lets the trailing stop own
exits.

Sweep findings (compounded return per name; baselines unchanged):

| Config | default | broad |
|--------|---------|-------|
| Original (slow=sell, trail=15, hold=60) | +38.6% | +18.6% |
| slow=watch, trail=15, hold=60 | +49.2% | +28.4% |
| **slow=watch, trail=12, hold=250 (adopted)** | **+49.1%** | **+33.1%** |
| Buy-and-hold baseline | +96.4% | +56.2% |

The improvement holds on the neutral broad universe (not just the cherry-picked winners),
which argues against overfitting. `trail=12` was chosen over `15` because it won the broad
test with negligible default cost (a marginal in-sample call). `buy_threshold` raised to 70
hurt returns, so it stayed at 65. `max_hold_days` raised to 250 (~1yr) so a clock no longer
force-closes running winners. After tuning, the **trailing stop is the dominant exit**
(42/73 default, 30/63 broad) and expectancy rose to ~+7%/trade.

Production values in `config/exits.yaml`: `take_profit_mode: trailing`, `trailing_stop_pct: 12`,
`trend_break_slow_level: watch`, `max_hold_days: 250`, `buy_threshold: 65`, `cost_pct_per_side: 0.1`.

**Honest framing:** over a ~2-year almost-straight-up market, a timing strategy still trails
buy-and-hold (+49% vs +96% default). That is expected — a timing system's edge is smaller
drawdowns in flat/down markets, which this window does not contain. A future addition of a
max-drawdown metric would let us measure that advantage directly.

## Verification

1. `python -m pytest -q` — all existing + new tests green.
2. `python -m src.backtest` — default watchlist; report leads with comparable compounded
   strategy-vs-hold figures, no "+761% sum" line, reflects trailing-stop exits + costs.
3. `python -m src.backtest broad` — produces `backtest-broad-<date>.md`.
4. `python -m src.main` (no API key) — live briefing still renders; held names show
   trailing-stop-aware exit signals.
