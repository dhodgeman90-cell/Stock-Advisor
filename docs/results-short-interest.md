# Results — does short interest predict forward returns? (pre-registered)

**Run 2026-11-25** on the owner's machine, `python -m src.short_interest`, at commit `2f23d3b`
(the study code is unchanged since). Pre-registration: `preregistration-short-interest.md`,
Amendment 1 committed (`5d2f720`) before any FINRA data was downloaded.

**Verdict: NEGATIVE_SIGNIFICANT. H1 (positive) is rejected.** Heavily shorted names went on to do
slightly *worse* — the literature-consistent direction, the opposite of the six-week pilot.

## Data

- FINRA consolidated short interest: 68,217 readings, 572 tickers, settlement dates
  **2021-11-15 → 2026-11-13** (FINRA's five-year window; nothing older was requested).
- 502 names had a usable short/shares-outstanding ratio on the last date.
- Point-in-time: readings usable from settlement + 8 business days; SEC shares outstanding from
  filing date; size + volatility neutralised; live $10M/day gate.

## Primary — short shares ÷ shares outstanding

| Horizon | All dates IC (t) | Pilot window excluded IC (t) | Days | IC > 0 |
|---|---|---|---|---|
| 5d | −0.0144 (−3.37) | −0.0151 (−3.48) | 1,248 | 43% |
| 10d | −0.0169 (−3.10) | −0.0176 (−3.21) | 1,243 | 41% |
| **21d (primary)** | **−0.0235 (−3.05)** | **−0.0239 (−3.05)** | 1,232 | 40% |
| 63d | −0.0395 (−3.33) | −0.0405 (−3.37) | 1,190 | 29% |

Per year at 21d: 2022 −0.036, 2023 −0.025, 2024 −0.021, 2025 −0.028, 2026 YTD −0.004.

Checks: sign ✗ (negative), |t| > 2.75 ✓, ≥ 3 of 4 positive full years ✗ (0 of 4), |IC| ≥ 0.02 ✓.
Identical with the pilot window excluded.

## Secondary — FINRA days to cover (reported, not decisive)

21d IC −0.0292 (t −4.56), every full year negative (−0.039, −0.028, −0.021, −0.047), 2026 YTD
−0.001. Same direction, slightly stronger.

## What this means

1. **The pilot was a short squeeze in a risk-on tape, as the pre-registration suspected.** Over
   five years the effect runs the other way, consistently in every full year, and both measures
   agree. The 2026-11 out-of-sample read of the live capture (`results-forward-capture-2026-11.md`)
   had already shown the pilot's sign failing.
2. **Pre-committed action: record it and stop.** This does **not** license flipping the
   `short_squeeze` cap. The live rule is conditional (+10 for ≥ 20% short with a strong chart or
   rising WSB chatter, −10 otherwise), which this cross-sectional study does not test directly.
   Leave `short_squeeze: 10` exactly where it is.
3. **The only signal in this repo with a real, stable, free-data result is negative and small**
   (IC ≈ −0.02 to −0.04). After the app's 0.2% round-trip cost and short-term tax, an "avoid
   heavily shorted names" filter is the most this could support, and it would need its **own**
   pre-registration and portfolio test. It is not a route to beating buy-and-hold.
