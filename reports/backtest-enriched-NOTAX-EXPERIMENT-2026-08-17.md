# Stock Advisor — Enriched Backtest (NOTAX-EXPERIMENT, 2026-08-17)

> ⚠️ **EXPERIMENT — stcg_tax_pct forced to 0. NOT a real after-tax result; for tax-drag attribution only.**

Window: **2022-05-10 → 2026-08-14** · names: **10**

> **Partial engine — read this first.** This replays the base technical score PLUS the only signals honestly reconstructable point-in-time on free data: SEC EDGAR 8-K / 13D (real filing dates). Estimated cap-budget coverage: **~15%**. EXCLUDED (no free as-of history): congress, insider, analyst, short interest, options flow, estimate revisions, WSB, and the AI news/risk/social agents; macro regime is deferred. So this is NOT validation of the full enriched engine — only of the part we can test honestly against history.

### Strategy vs buy-and-hold, per objective preset (after cost + short-term tax)
Equal-weight buy-and-hold baseline (untaxed): **+339.9%** per name · max drawdown **-27.9%**

| Preset | Enriched | Base | vs B&H | Win% | Expectancy | Trades | MaxDD | Exposure |
|---|---|---|---|---|---|---|---|---|
| Conservative | +136.8% | +136.8% | -203.1% | 40% | +17.4% | 70 | -19.9% | 71% |
| Balanced | +224.8% | +224.8% | -115.1% | 47% | +17.0% | 92 | -21.1% | 79% |
| Active | +160.6% | +160.6% | -179.3% | 42% | +6.5% | 175 | -21.5% | 75% |
| Aggressive Swing | +95.1% | +95.1% | -244.8% | 47% | +2.4% | 350 | -25.4% | 71% |

_Short-term-gains haircut on winning trades: 0% (buy-and-hold pays none — that's the hurdle daily trading must clear)._

## Verdict — NO measured edge
No preset's enriched, after-cost/after-tax return beat equal-weight buy-and-hold (**+339.9%**) over this window (best was **+224.8%**). Per the plan's kill criterion, daily-trading these names shows **no measured edge here — do not start P1 feature work on this evidence.** Grow the ledger (P0-b) and re-check across more regimes first.

### Per-regime — best preset vs buy-and-hold
A timing strategy can only beat buy-and-hold over a full cycle by LOSING LESS in the down/flat regimes. This splits the same run by market regime so that edge (or its absence) is visible, not averaged away by the bull run.

| Regime | Best preset | Return | MaxDD | Return/DD | B&H return | B&H MaxDD |
|---|---|---|---|---|---|---|
| 2022 selloff | Balanced | -10.2% | -15.6% | -0.65 | -14.4% | -27.6% |
| 2023 24 bull | Balanced | +106.7% | -21.3% | 5.01 | +255.9% | -20.1% |
| 2025 26 | Balanced | +51.0% | -19.5% | 2.62 | +58.7% | -28.1% |
| full | Balanced | +224.8% | -21.1% | 10.65 | +339.9% | -27.9% |

## Attribution — pre-registered interpretation
The gap vs buy-and-hold decomposes exactly as **G = Cash drag + Tax drag − Signal**, where **Cash drag = B&H − market-on-in-days** (return forgone while in cash), **Tax drag = strategy(no-tax) − strategy(after-tax)**, and **Signal = strategy(no-tax) − market-on-in-days** — what the scoring/exit stack added over passively riding the *same names on the same in-market days*. The universe is fixed (all names traded), so Signal is timing/exit skill, not stock-picking.

_Interpretation fixed BEFORE the run — the sign of Signal decides which holds:_
- **Signal > 0** — the stack beat passively holding those names on its in-market days. The engine adds value; the shortfall vs buy-and-hold is **structural** (tax + time out of market), not a signal failure.
- **Signal ≈ 0** — no better than passively holding those same names those same days. The scoring stack is **unproven** — no measurable edge from the signal logic.
- **Signal < 0** — earned *less* than passively riding those names would have. The scoring is **actively anti-predictive** — that is the headline finding.

| Preset | Exposure | Market-on-in-days | Cash drag (B&H−mkt) | Signal (enr−mkt) |
|---|---|---|---|---|
| Conservative | 71% | +134.9% | +205.0% | +1.9% |
| Balanced | 79% | +226.6% | +113.3% | -1.8% |
| Active | 75% | +167.6% | +172.3% | -7.0% |
| Aggressive Swing | 71% | +114.1% | +225.8% | -18.9% |
_Signal here uses THIS report's strategy return; in the after-tax control it is net of the tax haircut, so read the clean Signal off the no-tax experiment report._

> Caveat: partial-engine, single-window, free-data backtest. Overfitting and survivorship risk remain — confirm against the live scorecard as the ledger grows.

_Information only — not financial advice._
