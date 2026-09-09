# Pre-registration — does short interest predict forward returns in this universe?

**Written 2026-09-09. No test has been run. This document fixes the acceptance bar BEFORE any
number is computed**, following the precedent of `preregistration-8k-event-study.md`.

**Status: NOT IMPLEMENTED. The signal is not in the score and must not be added on the evidence
below.**

---

## Why this exists

The 2026-07-28 → 2026-09-09 signal capture (2,530 point-in-time records, 31 trading days, 512
tickers, candidate + random-control cohorts) was analysed for the first time on 2026-09-09.
Short interest as a percentage of float was the **only** signal in the set that behaved like a
real one:

| Cut (10d horizon, size + volatility neutralised) | IC | NW t | days |
|---|---|---|---|
| All rows | **+0.087** | +3.57 | 20 |
| **Control cohort only** (unbiased random draw) | **+0.168** | — ⚠️ | 14 |
| Candidates only | +0.093 | +3.00 | 20 |

It was positive on 68–86% of days, and stable across both halves of the window
(first half +0.057, second half +0.061 at 5d). Critically it got **stronger** under size and
volatility neutralisation (raw 10d IC was only +0.039), which is the opposite of what a factor
artefact does — `options.vol_oi_ratio` went the other way, from +0.094 raw to −0.003
neutralised, and was pure size.

⚠️ The control-cohort t-stat is computed on 14 overlapping cross-sections and is not
interpretable. `research.newey_west` now withholds t-stats in that regime; the number above is
recorded as it was measured, not as evidence.

## Why it is NOT being acted on

**The sign is backwards relative to roughly forty years of published evidence.** The
established finding is that heavily shorted stocks *underperform* — short sellers are, on
average, informed (Asquith/Pathak/Ritter 2005; Boehmer/Jones/Zhang 2008). A **positive** IC on
short interest is the classic signature of a **short squeeze in a risk-on tape**, not of a
durable edge, and 2026-07-28 → 2026-09-09 was exactly that: a large-cap, high-beta window in
which size alone carried an IC of +0.124/+0.133 and realised volatility +0.147 at 10d.

Two independent reasons to hold fire:

1. **The window is too short to fit anything.** 31 trading days is roughly 25 usable
   overlapping cross-sections. The same session demonstrated the cost of forgetting this: the
   app's own `base_score` measured 5d IC −0.078 on these six weeks and **−0.0049 on the
   restored ~7-year panel (1,773 cross-sections)** — the short window overstated the effect
   about sixteenfold.
2. **This repo has already been burned by exactly this move.** A post-hoc "the score is
   inverted" finding was acted on once and evaporated out of sample; the 8-K results document
   explicitly refused to flip `edgar_catalyst` to −15 for the same reason.

## Hypothesis

**H1.** Among liquid US equities, cross-sectional rank of short interest as a percentage of
float **positively** predicts forward excess return over SPY.

Direction is pre-declared as **positive** because that is what the pilot showed. Registering it
this way is deliberate: it means the far more likely literature-consistent outcome (a negative
coefficient) counts as a **failure of H1**, not as a result to be re-described afterwards.

- **Primary horizon: +21 trading days.** Declared in advance.
- Secondary, reported but not decisive: +5d, +10d, +63d.
- Returns are excess over SPY, size- and volatility-neutralised cross-sectionally
  (`research.rank_ic(..., neutralize=True)`), because the raw version is contaminated by the
  size tilt documented above.

## Data

- **Short interest history: FINRA bi-monthly consolidated short interest**, which is published
  free and covers all listed US equities back well over a decade. This is the point the whole
  test hangs on — unlike congress, analyst, options or WSB data, short interest **does** have a
  free, genuinely point-in-time archive, so this hypothesis is one of the very few enrichment
  signals that can be tested on history at all rather than only forward.
- Settlement-date lag must be respected: a reading is usable only from its **publication** date,
  never its settlement date. Any implementation must assert this the way
  `backtest.py:444` asserts EDGAR as-of safety.
- Prices: the restored deep cache (~7 years, 575 names ≥ 800 bars), via
  `research._load_price_panel`.
- Universe: the existing `config/universe.txt` screen, with the live $10M/day dollar-volume gate
  applied point-in-time.

## Acceptance bar — all four required, at the +21d primary horizon

1. **Sign** matches the pre-declared direction (positive).
2. **|t| > 2.75** under Newey-West with lag = horizon, computed on non-overlapping-equivalent
   sample size. The bar is above 1.96 deliberately, to deflate for the multiple horizons and
   cuts examined.
3. **Consistent in ≥ 4 of 6 calendar years** — the same sign, measured per year.
4. **|mean IC| ≥ 0.02** at the primary horizon. Set from what would actually be
   economically meaningful after the app's own costs: at 0.2% round-trip plus 25% short-term
   capital gains, a smaller edge cannot pay for the trade.

An additional standing condition, independent of the four above: **the effect must not be an
artefact of the six-week pilot window.** The test period must exclude 2026-07-28 → 2026-09-09
entirely, or report that sub-period separately and show the result holds without it.

## Pre-committed actions

- **All four pass** → propose a cap for `short_squeeze` sized to the measured effect, and only
  then run it through `backtest.validate_regime_overlay`'s portfolio gate before anything ships.
  Passing this study earns a *portfolio test*, not a place in the score.
- **Any one fails** → H1 is rejected. Record the result in `docs/results-short-interest.md`, and
  **leave the existing hand-set `short_squeeze: ±10` cap exactly where it is** — it has never
  been validated in either direction, and this study failing is not evidence for it either.
- **Sign is negative and significant** → this is the literature-consistent outcome. It does not
  license flipping the cap to −10 on this evidence alone; that would need its own
  pre-registration. Record it and stop.
- **Underpowered** (fails only the t or the year-consistency test, with the right sign and size)
  → classified "not rejected, underpowered", exactly as the 13D activist result was. **Not**
  "supported".

## Power, stated in advance

At ~6.5 usable years and a bi-monthly observation frequency, the minimum detectable IC at +21d
is roughly 0.03–0.04. **A null result therefore means "no large effect", not "no effect."** The
pilot's +0.087 is comfortably above that floor, so the test is capable of confirming the pilot
if the pilot is real.

---

**Reproduce the pilot:** `python -m src.research` (the "short pct_float" rows, neutralised
column). **Do not** read the 21d column's t-stats — they rest on 9 overlapping cross-sections
and are withheld for that reason.
