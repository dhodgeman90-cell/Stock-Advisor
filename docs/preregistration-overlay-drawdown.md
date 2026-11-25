# Pre-registration — does the regime overlay deliver its actual claim (smaller drawdowns)?

**Written 2026-11-25. No test has been run. This fixes the acceptance bar BEFORE any number is
computed**, as `results-medium-horizon-and-timing.md` standing conclusion 5 asks.

**Status: RUN 2026-11-25 — PROPOSE_OVERLAY. See `results-overlay-drawdown.md`.**
`regime_overlay` stays commented out in `config/watchlist.yaml` until the proposal is accepted.

---

## Why the old gate is retired, not re-run

`backtest.validate_regime_overlay` judged the overlay on a **stock-selection portfolio**, with
checks specified on return (`reports/backtest-regime-default-2026-07-27.md`: DO NOT SHIP, 3 of 4
FAIL). Two problems, both now documented elsewhere in this repo:

1. **It asked the wrong question.** The overlay's claim is drawdown reduction. A timing rule in a
   net-up market loses return by construction, so a return-based gate fails it whatever it does.
2. **Its portfolio is survivor-biased.** Every price file in `data/` belongs to a 2026 survivor,
   so no selection-based backtest here can be quoted as evidence (`CLAUDE.md`).

So the test moves to **SPY itself** — one instrument, continuous history, no survivorship — the
same footing as the monthly 200-day rule that now leads the briefing.

## What is compared

All three on SPY's own adjusted close, longest history in the owner's cache, through the last
completed month. A stance decided on day *t*'s close earns day *t+1*'s return (no look-ahead).
Out of the market earns **0%** (conservative: T-bills would help both timing rules equally).
**0.1% cost per switch**, the same as the 2026-09-09 timing study.

| Name | Rule |
|---|---|
| **B&H** | Always in SPY. |
| **MONTHLY** (incumbent, shipped) | In SPY while the last month-end close > 200-day SMA; re-decided only at month-ends. Exactly `market.monthly_trend_call`. |
| **OVERLAY** (candidate) | `market.apply_hysteresis(market.regime_series(spy))` with its shipped defaults (50/200 MA, 8% drawdown, confirm 3 down / 5 up), checked daily. In SPY when `risk_on`, cash when `risk_off` (`DEFAULT_EXPOSURE_MAP` is not used: the claim being tested is the timing, not a partial exposure). |

Sub-periods (start → latest), fixed: **1999, 2003, 2010, 2015**. If the cache does not reach
1999, the earliest start it supports replaces 1999 and that is stated in the results.

Reported, not decisive: CAGR, max drawdown, CAGR/|maxDD|, switches per year, and the crisis
windows dot-com 2000-03→2002-10, GFC 2007-10→2009-03, COVID 2020-02→2020-04, 2022.

## Acceptance bar

**A. The claim (drawdown).** In **every** one of the four sub-periods, OVERLAY's max drawdown is
at most **75%** of B&H's (|DD_overlay| ≤ 0.75 × |DD_bh|).

**B. Worth replacing the incumbent.** In **≥ 3 of the 4** sub-periods, OVERLAY's CAGR/|maxDD|
exceeds MONTHLY's.

## Pre-committed actions

- **A and B pass** → open a separate PR proposing OVERLAY as the briefing's market call in place
  of MONTHLY. Passing earns a proposal, not an automatic switch.
- **A passes, B fails** → the overlay works but is no better than the simpler shipped rule. Keep
  MONTHLY. The overlay stays off; record it as superseded.
- **A fails** → the overlay does not deliver its own claim. It stays off and is recorded as
  retired. Do not tune its parameters on this result: that would be fitting on the test.
- In every case the result goes in `docs/results-overlay-drawdown.md`, and the "does not beat
  buy-and-hold" statement is not re-litigated by this study: neither rule is expected to.

## Power, stated in advance

This is four overlapping sub-periods of one instrument, dominated by two or three crashes. It can
show whether the overlay's drawdown control is *real and comparable* to the incumbent's. It
cannot estimate a small difference between them precisely, which is why B asks for 3 of 4
rather than a margin.
