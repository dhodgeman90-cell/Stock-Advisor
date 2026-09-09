# Results — can a medium/long-horizon model beat buy-and-hold?

**Run 2026-09-09.** Question asked: the 5–21 day model has no edge, so would a medium-horizon
or long-hold model do better, and could anything beat buy-and-hold?

**Answer: no, not demonstrably.** The only part of the result that can be verified without paid
data is the part that *loses* return. The part that appeared to win cannot be separated from
survivorship bias.

The genuinely valuable finding is the one this repo has been asserting for months and had never
properly measured: **market timing buys a large drawdown reduction at the cost of some return.**
That now has 27 years of survivorship-free evidence behind it.

---

## 1. The headline test — 200-day-MA timing on SPY itself

SPY has no survivorship bias: it is one instrument with a continuous history. So applying the
classic trend rule to SPY *alone* isolates the timing component cleanly. Rule: hold SPY while it
is above its 200-day moving average, otherwise cash. Checked monthly, 0.1% per switch.

| Period | Buy & hold | With timing | Return | Drawdown |
|---|---|---|---|---|
| from 1999 | 8.7% CAGR, −55% DD | 7.7% CAGR, −29% DD | **lost** | **halved** |
| from 2003 | 11.4%, −55% | 9.5%, −26% | **lost** | **halved** |
| from 2010 | 14.1%, −34% | 10.0%, −27% | **lost** | better |
| from 2015 | 13.8%, −34% | 9.8%, −25% | **lost** | better |

Checking weekly (6.7% CAGR) or daily (6.1%) is **worse** than monthly — more whipsaw, more cost.

**Read:** timing loses 1–4 percentage points of annual return in every sub-period tested, and
halves the drawdown in every sub-period tested. It is not an edge; it is a trade. Risk-adjusted
(CAGR / |maxDD|) it only wins when a major crash falls inside the window — from 1999 it wins
(0.27 vs 0.16), from 2010 it loses (0.37 vs 0.42).

This is the well-replicated Faber (2007) result, and it is consistent with everything else in
this repo.

## 2. What appeared to beat buy-and-hold, and why it should not be believed

A top-20, monthly-rebalanced portfolio ranked by trend or momentum, over the same 27 years,
showed enormous outperformance (+17,000% to +28,000% vs SPY's +904%). Three reasons that number
is not real:

**a) The universe is 100% survivors.** Every ticker in `data/` exists in 2026. Eligible names by
year, all of them 27-year survivors:

| 2000 | 2003 | 2008 | 2012 | 2018 | 2026 |
|---|---|---|---|---|---|
| **70** | 90 | 242 | 271 | 404 | 561 |

A backtest whose year-2000 cross-section is 70 hand-selected-by-hindsight survivors cannot
support a claim about the year 2000.

**b) The survivorship gradient is measurable and steep.** Over the shorter 6.4-year window,
momentum 12-2 returned 1693% on today's ticker list → 691% restricted to names that existed and
were liquid in 2020 → **285%** restricted to the 200 most liquid names then. Each tightening
roughly halves it. Momentum's most-held names were CVNA, NVDA, APP, CELH, SMCI, PLTR — precisely
the famous winners of the period. 6.5% of the ticker list more than 10×'d.

**c) It does not survive the crises.** Always-invested trend ranking, per regime:

| Regime | SPY | trend rank | |
|---|---|---|---|
| dot-com 2000-03→2002-10 | −34% (DD −48%) | **−50%** (DD −56%) | lost |
| GFC 2007-10→2009-03 | −47% (DD −55%) | −45% (DD −57%) | tied, deeper DD |
| 2022 | −18% (DD −24%) | −17% (DD −37%) | tied, much deeper DD |

The full-period outperformance comes **entirely** from the bull phases. Drawdowns are *worse*
than buy-and-hold (−61% to −63% vs −55%) — the opposite of what this tool is for.

## 3. Two measurement bugs found and fixed during this work

**Lookahead in the portfolio harness.** The first run showed momentum at 1845% and the app's own
`base_score` at 1224% — impossible, since `base_score` has an IC of zero. Cause: weights were set
using day *d*'s close and then earned day *d*'s return. Because `base_score` selects names that
spiked *today*, it was collecting the spike it used to select. Measured: **+2.125% per rebalance
of pure lookahead vs +0.094% actually obtainable.** Corrected, `base_score` fell to 142% —
losing to SPY, exactly as its IC predicts.

**A too-strict universe filter.** A "names investable in 2019" filter returned 2 names, because
the index ETFs carry 29 more bars than everything else, putting real coverage at 0.889 against a
0.90 threshold. Corrected to 473 names.

Both were the instrument, not the market. Neither would have been visible without a sanity check
against a quantity whose answer was already known.

## 4. Free data cannot settle the remaining question

Verified 2026-09-09 against yfinance, testing 10 known S&P 500 members that failed or were
acquired (SIVB, FRC, SBNY, TWTR, ATVI, XLNX, CERN, DISCA, PBCT, BBBY):

- **8 of 10 returned no data at all.**
- **2 returned recycled tickers** — SBNY came back with bars starting 2024-08-15 for a bank that
  failed in March 2023; BBBY with bars from 2026-07-17 for a company bankrupt in 2023.

The second failure mode is worse than the bias: a naive point-in-time fetch would silently splice
an unrelated company into the history.

Historical membership *is* free — Wikipedia's "Historical components of the S&P 500" carries 723
dated changes spanning 1963–2026. Knowing which names left without being able to price them does
not remove the bias.

Priced options if this is ever revisited: **EODHD** ~$19.99/mo (delisted data included) paired
with the free Wikipedia membership list; or **Norgate Data** ~$630/yr, which bundles delisted
securities *and* historical index constituents back to 1950. Not purchased — the honest prior
after this work is that most of the apparent selection edge is survivorship.

## 5. The regime overlay gate, re-run on corrected arithmetic

`_ret_per_dd` was mathematically inverted for losing periods (`ret / abs(dd)` ranks a worse
drawdown as better when the return is negative). It feeds `calmar`, which decides kill-criterion
checks c1 and c4. Fixed and the gate re-run unchanged.

**Verdict unchanged: DO NOT SHIP, 3 of 4 checks still fail.** The fix did move one component —
in the 2022 selloff, overlay-ON now correctly ranks ahead of overlay-OFF (−28.67 vs −53.56)
where the old formula ranked it behind — taking check 4 from 0-of-3 to 1-of-3. Not enough.

This is the same finding as §1 from a different direction: the overlay trades return for
drawdown, and a gate specified on return will always fail it.

---

## Standing conclusions

1. **Nothing here beats buy-and-hold on return.** Five prior efforts said so; this one adds a
   survivorship-free 27-year test and agrees.
2. **The drawdown reduction is real, large, and now properly evidenced** — roughly halving max
   drawdown across every sub-period from 1999. That is a genuine product, and it is what
   `CLAUDE.md` already claims the tool is for. It had never been measured on clean data before.
3. **Longer horizons are still structurally better than 5-day** — they avoid the cost and
   short-term-tax drag that makes the daily cadence unwinnable — but "better" is not "positive".
4. **Do not quote any selection-based backtest from this repo as evidence.** Every price file
   here belongs to a 2026 survivor. Until a delisted-inclusive dataset exists, selection results
   are unfalsifiable and should be labelled as such.
5. If a gate is ever re-specified for the overlay, specify it on **drawdown**, which is the
   overlay's actual claim, and pre-register it before running.
