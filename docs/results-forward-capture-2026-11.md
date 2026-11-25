# Results — the forward signal capture, out of sample (2026-09-10 → 2026-11-24)

**Run 2026-11-25.** Question: the 2026-09-09 analysis used the first six weeks of
`data/signal_history.jsonl`. Eleven more weeks have accumulated since. Did anything it flagged
hold up on data it never saw?

**Answer: no.** Nothing is positive and stable, the one lead (short interest) reversed sign, and
the screen's own picks did **worse than a random draw** of eligible names.

Method: `research.forward_panel` / `cohort_contrast` / `rank_ic(..., neutralize=True)`, unchanged,
run on the capture rows dated **after** 2026-09-09 only (3,522 rows; 3,093 with a matured 5-day
window, 48 dates, 535 tickers). Prices from the owner's local daily cache. These are short,
overlapping windows: read t-stats as indicative, and 21d t-stats are withheld by design.

## 1. The screen vs a random draw (the unbiased read on the whole funnel)

| Horizon | Screen's candidates | Random control | Difference | t | days |
|---|---|---|---|---|---|
| 5d | −0.11% | +0.61% | **−0.71%** | −1.78 | 48 |
| 10d | −0.17% | +1.39% | **−1.56%** | −2.66 | 43 |
| 21d | +1.04% | +3.38% | **−2.34%** | n/a | 32 |

Returns are excess over SPY. The candidates trailed the random cohort at every horizon. This is
the same direction the scorecard shows (47% of 918 matured picks beat SPY at +5d), and it is
consistent with the ~7-year panel IC of zero plus the documented thin-name tilt — a slightly
negative selection, not an inverted one. Do **not** flip the score; that move has failed here
once already.

## 2. Each signal, size- and volatility-neutralised

| Signal | 5d IC (t) | 10d IC (t) | 21d IC | Pilot (6 wks) |
|---|---|---|---|---|
| base_score | −0.003 (−0.10) | −0.018 (−0.40) | −0.089 | −0.078 at 5d |
| analyst upside % | −0.051 (−2.31) | −0.056 (−2.36) | −0.048 | — |
| analyst coverage n | −0.014 (−0.55) | +0.017 (+0.43) | +0.062 | — |
| **short % of float** | **−0.019 (−0.51)** | **−0.016 (−0.42)** | +0.058 | **+0.087 at 10d** |
| options vol/OI | −0.033 (−1.25) | −0.021 (−1.10) | +0.007 | −0.003 at 10d |
| EDGAR Form 4 count | +0.021 (+0.83) | +0.024 (+1.13) | +0.013 | — |
| congress buys | +0.022 (+0.52) | −0.005 (−0.12) | +0.097 | — |

- **Short interest did not survive.** The pilot's +0.087 at 10d (the only signal that "behaved
  like a real one") is −0.016 out of sample, and −0.033 in the control cohort alone. This is what
  `preregistration-short-interest.md` predicted when it refused to act on the pilot: a squeeze in
  a risk-on tape, not a durable edge. The pre-registered FINRA history test is still the proper
  verdict, but its prior is now weaker.
- **Analyst upside is mildly negative** (higher targets, worse returns) at t ≈ −2.3. One window,
  found by looking: a hypothesis at most. It does not license flipping the analyst cap.
- Congress, Form 4 and options are noise at this sample size.

## Standing conclusions

1. Eleven weeks of genuinely out-of-sample data add a seventh confirmation: **the screen does not
   pick winners**, and its picks trailed a random draw over this window.
2. The pilot's short-interest lead **did not replicate**. Keep `short_squeeze` exactly where it is.
3. `adds_paused: true` remains correct. The monthly market call (SPY vs 200-day) is the only
   evidence-backed instruction the tool gives; see `results-medium-horizon-and-timing.md` §1.
