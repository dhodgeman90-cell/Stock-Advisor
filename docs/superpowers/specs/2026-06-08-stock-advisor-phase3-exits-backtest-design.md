# Stock Advisor — Phase 3 Design: Sell Side + Backtesting

**Date:** 2026-06-08
**Status:** Design approved — pending spec review → implementation plan
**Owner skill level:** Beginner — every command must be explained before running
**Builds on:** Phase 1 (deterministic core) and Phase 2 (AI crew + adjudicator), both merged to `master`
**Parent spec:** `docs/superpowers/specs/2026-06-08-stock-advisor-design.md` (Sections 7 & 8)

---

## 1. Scope

Phase 3 delivers two things:

1. **The sell side** — manual `positions.yaml`, a deterministic exit-signal engine, and a
   holdings section that leads the daily briefing.
2. **Backtesting** — replay the deterministic scoring engine over historical data
   (trade-by-trade), measure its edge, and compare to buy-and-hold.

**Explicitly out of scope (deferred to Phase 4):** Windows Task Scheduler automation
for hands-off morning runs. This keeps the Phase 3 branch focused and reviewable.

---

## 2. Guiding principle (consistent with Phase 1/2 "B+" architecture)

Math stays deterministic and backtestable; AI agents annotate but never drive.

- **`exits.py` is 100% deterministic** — stop-loss, take-profit, trend-break,
  momentum-fade. No AI, no network. Fully unit-testable. This is exactly what the
  backtest replays, so results are free and reproducible.
- **The Risk agent annotates held names but does not drive exits.** `main.py` may
  optionally run the existing `risk_agent` on the 1–3 held tickers and append a ⚠️
  note to the briefing (e.g. "earnings tomorrow"). It never overrides the
  deterministic signals — mirroring how the buy side keeps scoring deterministic and
  agents separate.

Baking the LLM into `exits.py` was rejected: it would make exits non-deterministic
and un-backtestable, breaking the core principle.

---

## 3. New config files

Follows the existing one-YAML-per-concern pattern (`watchlist.yaml`, `weights.yaml`,
`adjudicator.yaml`).

### `config/positions.yaml` — manual holdings (user edits on buy/sell)

```yaml
positions:
  - ticker: NVDA
    entry_price: 120.50
    entry_date: 2026-06-01
    shares: 2          # optional, for the user's own notes; not required by logic
    # optional per-position overrides (beat the defaults in exits.yaml):
    # stop_loss_pct: 10
    # take_profit_pct: 25
```

An empty or missing `positions:` list is valid → briefing shows "_No tracked positions_".

### `config/exits.yaml` — all tunable numbers (used by live exits AND backtest)

```yaml
defaults:
  stop_loss_pct: 8         # sell if price <= entry * (1 - 0.08)
  take_profit_pct: 20      # trim/sell if price >= entry * (1 + 0.20)
  trend_break_fast: 20     # watch/trim if close < 20-day MA
  trend_break_slow: 50     # sell if close < 50-day MA
  momentum_fade:
    rsi_was_above: 70      # had been overbought...
    volume_dry_ratio: 0.7  # ...and volume now < 0.7x its 20-day average
backtest:
  buy_threshold: 65        # simulate a buy when base score >= this
  max_hold_days: 60        # force-close a trade after N trading days
  window_years: 2          # how much history to replay
  baseline: equal_weight_watchlist
```

`config.py` gains `load_positions()` and `load_exit_rules()`, shaped like the existing
loaders (validate presence, raise `ValueError` on malformed input).

---

## 4. `src/exits.py` — deterministic sell-side engine

One job: given a holding, its validated price history, and the rules, return a
structured signal. Pure function — no I/O.

```python
evaluate_exit(df, position, rules) -> {
    "ticker": "NVDA",
    "current_price": 109.4,
    "pct_from_entry": -9.2,
    "signals": [                       # zero or more, in priority order (see table)
        {"type": "stop_loss", "level": "sell", "emoji": "🔴",
         "detail": "down 9.2% from entry (stop -8%)"},
    ],
}
```

### Exit signals and priority ordering

Evaluated and listed in this fixed priority order (the most actionable/urgent
decision first — stop-loss before take-profit, hard sells before soft watches):

| # | Signal | Trigger | Emoji / level |
|---|---|---|---|
| 1 | Stop-loss | `price <= entry * (1 - stop_loss_pct/100)` | 🔴 sell |
| 2 | Take-profit | `price >= entry * (1 + take_profit_pct/100)` | 🟢 trim/sell |
| 3 | Trend-break (slow) | `close < 50-day MA` | 🔴 sell |
| 4 | Trend-break (fast) | `close < 20-day MA` | 🟡 watch/trim |
| 5 | Momentum-fade | RSI was recently above `rsi_was_above` AND `volume_ratio < volume_dry_ratio` | 🟡 watch/trim |

- Reuses existing `indicators.sma`, `indicators.rsi`, `indicators.volume_ratio`.
- Per-position overrides (`stop_loss_pct`, `take_profit_pct`) take precedence over
  `defaults`.
- "RSI was recently above X" = the max RSI over a short recent window (e.g. last 5
  days) exceeded the threshold while today's RSI is lower (rolling over).
- A holding can return multiple signals; the briefing shows them all, in priority
  order.

---

## 5. `src/briefing.py` — holdings lead the briefing

Per the parent spec, exits appear **above** new candidates.

- Add `render_holdings_section(holdings)` returning the markdown block.
- `render_briefing(...)` gains a `holdings` argument and renders that section first,
  before "Top candidates".
- Each holding shows ticker, entry price, current price, % from entry, and its
  signal(s) with the "why". A held name with no triggered signal shows a 🟢 "holding —
  no exit signal" line.
- Include the reminder: "Keep `positions.yaml` current."
- No holdings → "_No tracked positions._"
- Optional ⚠️ Risk-agent annotation line appended per holding when available.

---

## 6. `src/main.py` — wire exits into the daily pipeline

- Build the fetch set as the **union of watchlist tickers + held tickers** (a holding
  may not be on the watchlist; it still needs price data for exit evaluation).
- After data fetch/validate, run `exits.evaluate_exit` on each holding (deterministic).
- If `ANTHROPIC_API_KEY` is present, optionally run the existing `risk_agent` on held
  tickers and attach a ⚠️ annotation. The no-key Phase 1 fallback path also renders the
  holdings section (deterministic signals still work without AI).
- Prepend the holdings section to the briefing. The buy-side flow is otherwise
  unchanged.
- Graceful failure preserved: a holding that fails data validation shows a clear note,
  never a fabricated signal.

---

## 7. `src/backtest.py` — replay the engine on history (free, no AI)

Trade-by-trade simulation measuring the deterministic engine's edge.

### Method
- For each watchlist ticker, fetch `window_years` of daily history (reuse
  `data.fetch_history` with a larger day count; cache to `data/`).
- Walk forward day-by-day. When `base_score >= buy_threshold` and no trade is currently
  open on that ticker → **open a simulated trade at the next day's open** (avoids
  look-ahead bias).
- On each subsequent day, evaluate `exits.py` rules **against that day's close**
  (conservative — no intrabar/fantasy fills); also force-close at `max_hold_days`.
- Record per trade: ticker, entry date/price, exit date/price, return %, hold days,
  exit reason.
- One open trade per ticker at a time (no pyramiding).

### Baseline
Buy-and-hold the watchlist **equal-weighted** over the same window — apples-to-apples
on the same universe (chosen over SPY).

### Report → `reports/backtest-YYYY-MM-DD.md`
- Number of trades, win rate, average gain vs average loss, average hold time.
- Total strategy return vs buy-and-hold baseline.
- Breakdown of which exit rule closed each trade (how often each fires).
- The honest overfitting caveat from the parent spec (a good backtest is encouraging,
  not a guarantee; treat results skeptically).

### Run command
```powershell
& .\.venv\Scripts\python.exe -m src.backtest
```

---

## 8. Testing (TDD, matching the existing ~35-test discipline)

- **`tests/test_exits.py`** — synthetic DataFrames (via existing `tests/helpers.py`):
  each signal fires exactly at its boundary and not just below it; per-position
  overrides win; severity ordering is correct; multiple simultaneous signals; a clean
  holding returns no signals.
- **`tests/test_backtest.py`** — a crafted price series produces one known winning trade
  and one known losing trade with the expected exit reasons; the buy-and-hold baseline
  math is correct; no look-ahead (entry uses next-day open); `max_hold_days` force-close
  works.
- **`tests/test_config.py`** — extend with `load_positions()` / `load_exit_rules()`
  happy-path and malformed-input cases.
- **`tests/test_briefing.py`** — extend: holdings section renders, empty-holdings line,
  signals shown in priority order.

Every new branch covered. Tests use injected fakes / synthetic data — no network, no
real AI calls.

---

## 9. Files touched

| File | Change |
|---|---|
| `config/positions.yaml` | **new** — manual holdings |
| `config/exits.yaml` | **new** — exit thresholds + backtest params |
| `src/config.py` | add `load_positions()`, `load_exit_rules()` |
| `src/exits.py` | **new** — deterministic exit engine |
| `src/backtest.py` | **new** — trade-by-trade replay + report |
| `src/briefing.py` | add `render_holdings_section`; holdings lead `render_briefing` |
| `src/main.py` | fetch union set; evaluate exits; optional Risk annotation; prepend section |
| `tests/test_exits.py` | **new** |
| `tests/test_backtest.py` | **new** |
| `tests/test_config.py` | extend |
| `tests/test_briefing.py` | extend |
| `README.md` | document `positions.yaml`, exit signals, backtest command |

---

## 10. Rollout (unchanged from parent spec)

Backtest (free) → paper-trade a few weeks (track picks without real money) →
real money. Phase 4 then automates the morning run via Task Scheduler.

## 11. Open items carried into the build

- Confirm the exact recent-window length for the momentum-fade RSI "was overbought"
  check (proposed: 5 days).
- Decide whether held tickers absent from the watchlist should also appear in the
  buy-side scan or only in the holdings section (proposed: holdings section only).
- Initial real watchlist contents still to be finalized (carried from parent spec; the
  backtest works on the current placeholder list in the meantime).
