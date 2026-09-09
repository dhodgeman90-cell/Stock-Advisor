# Stock Advisor — Claude Code Guide

## What this is

A **local, free** tool that scans a watchlist and prints/emails a ranked list of short-term
momentum buy candidates.

> **It suggests only. It never trades.** Nothing in this codebase places an order.

- **Local path:** `C:\VS Code\Stock Advisor`
- **Repo:** `github.com/dhodgeman90-cell/Stock-Advisor` — ⚠️ **PUBLIC**
- **Owner skill level:** Beginner — always explain commands before running them.

---

## ⚠️ READ THIS BEFORE PROMISING ANY PERFORMANCE

**No configuration of this tool beats buy-and-hold in the 2022–2026 window.** This has been
independently confirmed **four times**, most rigorously by a portfolio-level walk-forward
backtest with a pre-registered kill criterion (`backtest.validate_regime_overlay`).

- Best fixed default: **+159%** vs buy-and-hold **+224%**.
- The regime overlay wins the 2022 crash (−23% vs −45%) but loses the full window.
- This is **structural, not a bug**: a stop-based timing strategy loses to buy-and-hold in a
  net-up market — being out during pullbacks means missing the recovery.

**What the tool is actually for:** lower drawdown, downturn protection, and *idea surfacing*.
It is a **risk-managed systematic idea generator, not an index beater.** Say so plainly.

### The drawdown claim is now MEASURED, survivorship-free — 2026-09-09

The 200-day-MA timing rule applied to **SPY itself** (one instrument, no survivorship possible),
checked monthly over 27 years. See `docs/results-medium-horizon-and-timing.md`.

| From | Buy & hold | With timing |
|---|---|---|
| 1999 | 8.7% CAGR, −55% DD | 7.7% CAGR, **−29% DD** |
| 2003 | 11.4%, −55% | 9.5%, **−26%** |
| 2010 | 14.1%, −34% | 10.0%, **−27%** |
| 2015 | 13.8%, −34% | 9.8%, **−25%** |

**Loses return in every sub-period. Halves drawdown in every sub-period.** Checking weekly or
daily is worse (whipsaw). This is the first properly-powered, bias-free evidence for the claim
this file has been making all along — and it is also the sixth independent confirmation that
nothing here beats buy-and-hold on return.

⚠️ **Never quote a selection-based backtest from this repo as evidence.** Every CSV in `data/`
belongs to a 2026 survivor. Eligible names by year — all 27-year survivors: **70** (2000), 90
(2003), 242 (2008), 404 (2018), 561 (2026). A top-20 trend portfolio "returns" +17,000% over
that panel; the same idea restricted toward an investable universe collapses toward the index,
and it *loses* the dot-com bust (−50% vs SPY −34%) with deeper drawdowns throughout.
yfinance cannot fix this: of 10 known delisted S&P names, **8 return nothing and 2 return
recycled tickers** (SBNY serves bars from 2024 for a bank that failed in 2023).

### The score carries no information — measured on ~7 years, 2026-09-09

`research.panel_ic` on the restored deep cache (1,856 dates × 575 tickers, ~1,800 daily
cross-sections) puts `base_score`'s rank IC vs forward excess return at:

| 5d | 10d | 21d | 63d |
|---|---|---|---|
| −0.0049 (t=−0.67) | −0.0058 (t=−0.65) | −0.0093 (t=−0.79) | −0.0295 (t=−1.86) |

IC > 0 on ~50% of days. Per year at 21d it flips sign with no stability: −0.104, −0.034,
−0.011, **+0.009**, −0.004, **+0.032**, −0.010, −0.011.

**The score is not inverted and not anti-predictive. It is indistinguishable from zero.**
Do not "fix the sign" — that move has already failed here once.

⚠️ **The six-week window overstates everything by roughly 16×.** The same test on
`signal_history.jsonl` alone (25 usable overlapping cross-sections) gave 5d IC −0.078. Treat
any result from that file as a hypothesis, never as a fitted parameter. Run
`python -m src.research` — it prints both, side by side, deliberately.

**The unintended exposure:** the top-8 sits at a median **0.90×** the dollar volume of the pool
it was screened from, and is thinner on 60% of days, every year 2020–2026 (0.86×–0.97×).
`breakout(30) + volume(30)` prefers thinner names. Small, persistent, uncompensated — the
briefing now shows each name's `$vol/day` and realised vol rather than carrying it silently.

Also honest-scope: **only ~25% of the signal engine is point-in-time backtestable** on free
data (base technicals + SEC EDGAR). Congress / analyst / options / insider / short-interest /
revisions / AI signals can only ever be proven **forward**, via the live scorecard ledger.
Never describe those as backtest-proven.

---

## Current live state — verify, don't assume

Read `config/watchlist.yaml` before describing behaviour. As of 2026-08-13:

| Flag | State | Why |
|---|---|---|
| `ai_mode` | **off** | The news/risk/social agents drove 223 of 353 "Buy:" verdicts ever printed on **zero** validation. Switched off, not deleted — unvalidated is not refuted. `measure` runs them, captures to `data/ai_history.jsonl`, and gives them **no** influence on score, verdict or page; that is the only route to ever answering whether they work, and it costs a few cents a day. `live` is the legacy default. |
| `quiet_unless_actionable` | **true** | Email only when a holding trips an exit rule. The run and the daily signal capture continue regardless — only the notification stops. |
| `adds_paused` | **true** | BUY calls withheld — **not** "pending validation" any more; validation happened six times. The sell side (exits/trims on open positions) stays fully live; candidates are still scored and shown — labelled **`Candidate`**, never `Buy`. ⚠️ Until 2026-09-09 this flag zeroed only the rotation adds while the shortlist kept printing "Buy" for eight names a morning (332 such verdicts shipped). `verdict.classify(..., adds_paused=True)` now enforces it, guarded end-to-end in `tests/test_main.py`. |
| `entry_model: relative_strength` | **commented OUT** | The 2026-07-27 P0 audit disabled it: RS is renormalized inside an already-weak 25-name pre-filtered pool, and it has zero backtest and zero forward test. |
| `regime_overlay` | **commented OUT** | Its own kill criterion returned **"DO NOT SHIP"** (3 of 4 checks FAIL) in `reports/backtest-regime-default-2026-07-27.md`. |

⚠️ Both flags were briefly enabled in commit `163267f`, then **turned back off** by the later
P0 audit (`6ffbe9c`, `8c3d9ee`). Any note claiming the RS-entry forward test is running is
**stale** — it is not, and no forward-test data is accumulating for it.

---

## Commands

```powershell
# Run the briefing (CLI)
python -m src.main

# Run the local browser dashboard (FastAPI on 127.0.0.1, never network-exposed)
python -m src.app

# Run the tests — 612 tests, ~31s
./.venv/Scripts/python.exe -m pytest -q

# Regime-overlay validation gate
python -m src.backtest --regime

# Rank-IC harness: does a signal actually order the cross-section?
# Prints the 6-week enrichment-signal table AND the ~7-year price-panel version.
python -m src.research

# Refill the deep price cache (~7y x 590 names, ~20s). Safe to re-run: since the
# save_cache fix the daily briefing no longer overwrites it.
./.venv/Scripts/python.exe scripts/fetch_deep_history.py
```

Always use `./.venv/Scripts/python.exe`, not bare `python` — the venv holds the deps.

---

## CI

`.github/workflows/ci.yml` runs the full suite on every push to `main` and every pull request
(`ubuntu-latest`, Python 3.14). It is safe on Linux because `conftest.py` installs a
`FakeKeyring` via an `autouse` fixture — **no test ever touches the real OS credential store.**

Keep it green. If it goes red, fix the cause; do not disable the check.

---

## Secrets

- **Never** commit `.env` — it is gitignored, and history has been scanned clean.
- `.env.example` is a template with **empty** values. Keep it that way.
- Live keys go in the **OS credential manager** (Windows Credential Manager / macOS Keychain)
  via `src/secrets_store.py` — never a plaintext file.
- The repo is **public**, so treat every file as world-readable before committing.

---

## Architecture notes

- **Profile-aware:** `main.run()` takes a `Profile` (config/data/reports dirs + secret source).
  No argument → `Profile.for_repo()`. A packaged per-user build passes
  `Profile.for_base(%APPDATA%/StockAdvisor)` so each user's data is isolated.
- `rank_score` (uncapped) is what the shortlist sorts by; `final_score` is the clamped 0–100
  **display** value. Sorting by `final_score` was the original score-saturation bug — don't
  reintroduce it.
- Liquidity filter is **dollar-volume ($10M/day)**, not share count. Share count wrongly
  excluded liquid high-priced names.
- Exits: 8%/20% + ATR 2.5× in `config/exits.yaml`. Tighter stops (the old 5%/6%) churn out of
  every winner — loosening them 3.5×'d the default preset's after-cost return.
- **`data.save_cache` MERGES, it does not overwrite.** It used to be a bare `to_csv`, and since
  the daily run refetches only 300 calendar days it destroyed the 7-year cache every morning
  (median depth was 204 bars; 3 of 589 files had a year). The merge is re-adjustment-aware:
  `yfinance` runs `auto_adjust=True`, so a split re-scales the whole series retroactively and a
  naive append would fabricate a price cliff. `_merge_history` takes the **median close ratio
  across the overlap**, rescales the old tail onto the new basis, inverse-scales Volume, and
  refuses to splice at all if that ratio isn't near-constant (IQR > 0.5%). Don't "simplify" it
  back to a concat.
- **The briefing shows a screen position, not a score.** 61% of logged picks used to pin at
  exactly `final_score` 100.0. `rank N of M` always discriminates. The ledger now also stores
  `rank_score`, `pool_rank`, `pool_size`, `run_at` and `bar_date`.
- **`bar_date` is the grading anchor, not `date`.** `_drop_incomplete` withholds an open
  session's bar, so a pre-open run scores off yesterday and a post-close run off today. Nothing
  recorded which until 2026-09-09; classifying the 528 legacy rows found 33% prior-bar, 9%
  same-date, 37% neither. Legacy rows cannot be repaired — exclude, don't average.
- `_ret_per_dd` branches on the sign of the return **on purpose**. `ret / abs(dd)` inverts for
  losing periods (a worse drawdown scored better), which corrupted regime kill-criterion checks
  c1 and c4.

---

## Rules for Claude

1. **Never claim this beats the market.** See the finding above. State the drawdown/idea-surface
   value instead.
2. **Use TDD** — this project is test-driven (612 tests). Write the failing test first
   (`superpowers:test-driven-development`).
3. **Verify live config before describing behaviour** — flags have been flipped both ways.
4. **Always explain commands** before running them; the owner is a beginner.
5. **No shortcuts, no bandaids** — do it properly or flag it and ask.
6. Never weaken a test to make it pass.
