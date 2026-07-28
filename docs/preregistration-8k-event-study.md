# Pre-registration — EDGAR 8-K event study

**Written 2026-07-27, BEFORE any result was computed.** The point of writing it first is that
the acceptance bar cannot move after seeing the data. If a hypothesis below fails, it failed —
we do not re-cut it by sector, sub-period, or item code until something passes. That practice
is what produced the unreproducible "walk-forward sweep" whose parameters this repo shipped
for a month.

## Why this study

The adjudicator assigns `edgar_catalyst: 15`, `edgar_severe: 20` (via `risk_high`) and
`activist_stake: 12` points. Those values were hand-set and have never been validated against
anything. This asks whether they are earning their keep.

EDGAR is also the *only* signal family in this app with genuine point-in-time history. Congress
trades (FMP 402 / StockWatcher 403), insider direction (402), and analyst / options / short
interest / WSB (present-day snapshots only) cannot be backtested at any price with free data —
see `src/signal_log.py`, which begins capturing them forward from today.

## Data

- **Universe**: `config/universe.txt` ∪ watchlist, ~577 names with ≥800 daily bars.
- **Prices**: `data/*.csv`, 2019-04-22 → 2026-07-27 (median 1826 bars), `auto_adjust=True`.
- **Events**: `data/edgar_filings.json` — SEC submissions API, real filing dates. Heavy filers'
  archive files are pulled so 8-K coverage is not systematically thinner for large financials
  in early years.
- **Point-in-time rule**: an event dated `d` is only visible on bars `> d`. Reuses the existing
  `edgar.signal_asof` semantics. A filing dated after the decision bar must never be counted.
- **Benchmark**: SPY. All returns are excess over SPY across the identical bar span.

## Hypotheses

| # | Signal | Direction | Rationale |
|---|---|---|---|
| H1 | 8-K catalyst items (1.01, 2.01, 2.02, 5.02) filed in trailing 30d | **positive** | The `edgar_catalyst: +15` cap assumes this |
| H2 | 8-K negative items (1.02, 2.06, 4.01) | **negative** | The `edgar_catalyst: -15` adverse branch |
| H3 | 8-K severe items (1.03, 2.04, 3.01, 4.02) | **negative** | The `risk_high: -20` cap |
| H4 | SC 13D activist stake | **positive** | The `activist_stake: +12` cap |
| H5 | Form 4 filing intensity (count in trailing 30d) | **positive** | Insider-activity proxy; direction unavailable without parsing each filing's XML |

## Acceptance bar (fixed in advance)

A hypothesis is **supported** only if all four hold:

1. **Sign** matches the prediction above.
2. **|t| > 2.75** on non-overlapping forward windows. Not 1.96 — the higher bar deflates for
   the ~5 hypotheses × 3 horizons = 15 comparisons run here, plus the ~8 price signals already
   tested on this same panel today.
3. **Sign consistency**: same sign in ≥4 of the 6 full calendar years (2020–2025).
4. **Economic size**: mean excess return ≥ 0.30% per event at the tested horizon — below that,
   0.2% round-trip costs consume it and it is not tradeable regardless of significance.

Horizons: +5d, +21d, +63d. Primary horizon is **+21d** (chosen in advance: long enough for the
0.2% round-trip cost to be survivable, short enough to retain sample size).

## Pre-committed consequences

- **If a hypothesis passes all four**: it earns a walk-forward test on a quarantined holdout
  (2019–2021, never yet read by any backtest in this repo) before any config change.
- **If a hypothesis fails**: the corresponding adjudicator cap is reduced toward 0, or the
  signal is demoted to display/veto only. A failed signal must not keep silently moving scores.
- **If everything fails**: that is a real, publishable-to-yourself result. The event family is
  dropped from ranking, the app is honest about being a position monitor, and no further hours
  go into price- or EDGAR-derived selection. We do **not** respond by inventing new cuts.

## Known limitations, stated up front

- 8-K item 2.02 (earnings) is filed without the **surprise** — we know earnings were reported,
  not whether they beat. Most documented post-earnings drift is conditioned on surprise, so
  this test is materially weaker than the academic version and a null result here does not
  refute PEAD.
- Form 4 count mixes purchases, routine sales, and option grants. Only insider *buying* has
  strong academic support; that requires per-filing XML parsing (~500 filings × 577 tickers),
  which is out of scope here.
- Universe is present-day S&P 500 + a hand-added mid/small-cap supplement: survivorship-biased.
  This inflates absolute returns but affects event and non-event names alike, so the
  event-vs-baseline *contrast* is far less exposed than any absolute figure.
- ~6.3 usable years. At +21d that is ~74 non-overlapping periods, which can only detect fairly
  large effects (see the power analysis run 2026-07-27: minimum detectable IC ≈ 0.063 at +21d).
  **A null result here means "no large effect", not "no effect".**
