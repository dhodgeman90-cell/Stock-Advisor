# Stock Advisor — Enriched Backtest (default, 2026-07-27)

Window: **2022-04-19 → 2026-07-27** · names: **10**

> **Partial engine — read this first.** This replays the base technical score PLUS the only signals honestly reconstructable point-in-time on free data: SEC EDGAR 8-K / 13D (real filing dates). Estimated cap-budget coverage: **~25%**. EXCLUDED (no free as-of history): congress, insider, analyst, short interest, options flow, estimate revisions, WSB, and the AI news/risk/social agents; macro regime is deferred. So this is NOT validation of the full enriched engine — only of the part we can test honestly against history.

### Strategy vs buy-and-hold, per objective preset (after cost + short-term tax)
Equal-weight buy-and-hold baseline (untaxed): **+240.1%** per name · max drawdown **-34.3%**

| Preset | Enriched | Base | vs B&H | Win% | Expectancy | Trades | MaxDD |
|---|---|---|---|---|---|---|---|
| Conservative | +99.2% | +82.2% | -140.9% | 40% | +13.2% | 72 | -22.3% |
| Balanced | +154.6% | +142.6% | -85.5% | 49% | +13.3% | 90 | -23.3% |
| Active | +97.7% | +87.0% | -142.3% | 45% | +4.5% | 178 | -22.4% |
| Aggressive Swing | +20.6% | +24.8% | -219.5% | 49% | +1.0% | 374 | -34.4% |

_Short-term-gains haircut on winning trades: 25% (buy-and-hold pays none — that's the hurdle daily trading must clear)._

## Verdict — NO measured edge
No preset's enriched, after-cost/after-tax return beat equal-weight buy-and-hold (**+240.1%**) over this window (best was **+154.6%**). Per the plan's kill criterion, daily-trading these names shows **no measured edge here — do not start P1 feature work on this evidence.** Grow the ledger (P0-b) and re-check across more regimes first.

### Per-regime — best preset vs buy-and-hold
A timing strategy can only beat buy-and-hold over a full cycle by LOSING LESS in the down/flat regimes. This splits the same run by market regime so that edge (or its absence) is visible, not averaged away by the bull run.

| Regime | Best preset | Return | MaxDD | Return/DD | B&H return | B&H MaxDD |
|---|---|---|---|---|---|---|
| 2022 selloff | Balanced | -3.8% | -18.0% | -0.21 | -31.2% | -34.3% |
| 2023 24 bull | Conservative | +73.6% | -19.0% | 3.88 | +255.9% | -20.1% |
| 2025 26 | Balanced | +43.1% | -23.3% | 1.85 | +48.6% | -28.1% |
| full | Balanced | +154.6% | -23.3% | 6.63 | +240.1% | -34.3% |

> Caveat: partial-engine, single-window, free-data backtest. Overfitting and survivorship risk remain — confirm against the live scorecard as the ledger grows.

_Information only — not financial advice._
