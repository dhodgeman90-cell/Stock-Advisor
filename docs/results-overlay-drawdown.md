# Results — does the regime overlay deliver smaller drawdowns? (pre-registered)

**Run 2026-11-25** on the owner's machine, `python -m src.timing_study`, commit `f9f4ca4`.
Pre-registration: `preregistration-overlay-drawdown.md` (committed before this run, `3d6c0b2`).
SPY 1995-01-03 → 2026-10-30 (last completed month). Next-day execution, 0% in cash, 0.1% per switch.

**Verdict: PROPOSE_OVERLAY.** Check A (drawdown ≤ 75% of buy-and-hold in every sub-period) and
check B (beats the shipped monthly rule on CAGR/|maxDD| in ≥ 3 of 4) both pass, B in 4 of 4.
Pre-committed action: a **separate** PR proposing the overlay as the briefing's market call.

**It does not beat buy-and-hold.** Its CAGR is below buy-and-hold in every sub-period, by 1.5 to
5 points a year. What it buys is a smaller worst drop: about −21% instead of −34% to −55%.

## Sub-periods (decisive)

| From | Rule | CAGR | Max DD | CAGR/\|DD\| | Switches/yr |
|---|---|---|---|---|---|
| 1999 | buy & hold | 8.6% | −55.2% | 0.16 | 0 |
| | monthly 200d | 8.0% | −27.9% | 0.29 | 1.3 |
| | **overlay** | 7.1% | **−21.0%** | **0.34** | 2.0 |
| 2003 | buy & hold | 11.3% | −55.2% | 0.20 | 0 |
| | monthly 200d | 9.0% | −27.9% | 0.32 | 1.3 |
| | **overlay** | 8.8% | **−20.7%** | **0.42** | 2.0 |
| 2010 | buy & hold | 13.9% | −33.7% | 0.41 | 0 |
| | monthly 200d | 8.2% | −27.9% | 0.30 | 1.7 |
| | **overlay** | 9.1% | **−20.7%** | **0.44** | 2.0 |
| 2015 | buy & hold | 13.5% | −33.7% | 0.40 | 0 |
| | monthly 200d | 6.8% | −27.9% | 0.24 | 2.0 |
| | **overlay** | 8.5% | **−20.7%** | **0.41** | 2.2 |

## Crisis windows (reported, not decisive — CAGRs are annualised over a few months)

| Window | B&H DD | Monthly DD | Overlay DD |
|---|---|---|---|
| dot-com 2000-03→2002-10 | −47.5% | **−12.4%** | −18.4% |
| GFC 2007-10→2009-03 | −55.2% | **−9.9%** | −10.8% |
| COVID 2020-02→2020-04 | −33.7% | **−12.4%** | −19.0% |
| 2022 | −24.5% | −23.8% | **−17.0%** |

The monthly rule had the smaller drawdown in the three classic crashes. The overlay's smaller
full-period drawdown therefore comes from elsewhere; 2022 is the one visible case here, and the
episode behind the monthly rule's −27.9% has not been located yet. In the COVID V-shape the
overlay lost more than buy-and-hold over the window (annualised −50.6% vs −35.3%), despite a
smaller drawdown.

## Things to know before acting on this

1. **This harness's monthly rule earns less than the 2026-09-09 study reported** (from 2010:
   8.2% here vs 10.0% there; from 2015: 6.8% vs 9.8%). The earlier study's code was not committed,
   so the difference cannot be traced. Likely contributors: this harness executes on the first
   session of the month (one day later), and credits 0% on cash where T-bills paid 4–5% in
   2023–2026. Both handicaps apply to the overlay equally, so check B is a fair comparison, but
   absolute CAGRs here are conservative.
2. One instrument, four overlapping periods, a handful of crashes. This shows the overlay's
   drawdown control is real and at least comparable; it does not pin down by how much it is better.
3. The overlay trades more (≈2 switches/yr vs 1.3–2.0) and is checked daily, so it would make the
   market call change mid-month. That is a product change, which is why the action is a proposal.
