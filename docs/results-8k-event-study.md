# Results — EDGAR 8-K event study

**Run 2026-07-27** against `docs/preregistration-8k-event-study.md`. The bar was fixed before
any number was computed and has not been moved.

Data: 577 tickers × 1826 bars (2019-04-22 → 2026-07-27); EDGAR filings for 581 tickers,
292 archive files pulled so heavy filers aren't systematically thin in early years; 523/581
reach 2019H1. Point-in-time logic verified on synthetic data: an event is invisible on and
before its filing bar, visible from the next bar, and expires at 30 calendar days.

## Verdict — all five hypotheses FAIL

| # | Signal | +21d (primary) | t | years | verdict |
|---|---|---|---|---|---|
| H1 | 8-K catalyst | **−0.445%** | **−2.87** | 1/6 | fail — *sign is opposite the prediction* |
| H2 | 8-K negative | +0.067% | +0.16 | 3/6 | fail |
| H3 | 8-K severe | n=1 | — | — | insufficient |
| H4 | 13D activist | −0.167% | −0.39 | 3/6 | fail |
| H5 | Form 4 intensity | −0.006% | −0.04 | 2/6 | fail |

## The two findings that matter

**1. `edgar_catalyst: +15` is contradicted by its own data.** At the primary horizon the
point estimate is **negative** (−0.445%, t=−2.87), and 5 of 6 years lean the same way. The cap
assumes a positive catalyst effect. The data does not merely fail to support that — it leans
against it.

Stated carefully: this does **not** license flipping the sign to −15. That is the identical
post-hoc move that produced a bogus "the score is inverted" finding earlier the same day, which
then evaporated out of sample. A negative catalyst effect is a *new* hypothesis and would need
its own pre-registered out-of-sample test on the quarantined 2019–2021 window.

**2. Two of these "events" are not events.** Share of eligible name-days with the signal live:

```
catalyst   49.64%     <- fires on HALF the universe at any moment
form4      75.46%     <- fires on three quarters
negative    1.60%
activist    2.12%
severe      0.25%
```

8-K item 2.02 is filed quarterly by essentially every company, so "catalyst live" is close to
"reported earnings in the last 30 days" — a near-constant, not a differentiator. A cap that
fires on half the cross-section shifts nearly every score by the same +15 and therefore cannot
change relative ranking; it only moves names across the 65 buy threshold. That is a design
defect independent of the sign question.

## Closest to a signal (still not a pass)

`13D activist` at **+63d: +3.298%, t=+2.23, 4/6 years, size +** — correct sign, correct
consistency, economically meaningful, but t below the pre-registered 2.75 and n=19. Classified
**not rejected, underpowered** — not "supported". It is the one EDGAR signal worth revisiting
when more data exists, which is consistent with its rarity (2.1% coverage) being what makes it
informative and simultaneously what makes it hard to test.

## What this does NOT test

- **The `insider_buy: +12` / `insider_sell: −10` caps.** Those read yfinance
  `.insider_transactions` for buy/sell *direction*. H5 tested EDGAR Form 4 *count*, which mixes
  purchases, routine sales and option grants. The insider caps remain untested, not refuted.
- **Congress, analyst, options, short interest, WSB.** No historical data exists at the free
  tier (FMP per-symbol endpoints return 402; StockWatcher archives 403). `src/signal_log.py`
  now captures these forward from 2026-07-27 so they become testable in 6–12 months.
- **Post-earnings-announcement drift.** 8-K 2.02 tells us earnings were reported, never whether
  they beat. Most documented PEAD is conditioned on surprise. A null here does not refute PEAD.

## Pre-committed action taken

Per the pre-registration ("a failed signal must not keep silently moving scores"):

- `edgar_catalyst` 15 → **0**. Unsupported and contradicted; it also fires on half the universe.
  The 8-K text remains in the briefing as *explanation*, which is what it is good for.
- `activist_stake` 12 → **6**. Halved rather than zeroed: right sign, right size, underpowered.
- `risk_high` (the 8-K severe path) **unchanged at −20**. Untestable here (n=1 at 21d) and
  retained on risk-control grounds, not alpha grounds — bankruptcy, delisting, default and
  restatement flags are worth avoiding whether or not they are tradeable.
- All untested caps unchanged.

## Standing conclusion

Combined with the same day's price-signal work — 8 candidate signals including 12-1 momentum
and relative strength, none reaching |t| > 1.3 across 7 years — **no signal family in this
repo has demonstrated a measurable edge.** The honest position is that the app is a validated
position monitor and an unvalidated stock picker, and `adds_paused: true` should stay set.

The instrument built today (verified 7-year panel + non-overlapping IC harness + point-in-time
event flags) is reusable and has now falsified three plausible claims, two of them mine.
