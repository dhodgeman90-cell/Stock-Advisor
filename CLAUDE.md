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

Also honest-scope: **only ~25% of the signal engine is point-in-time backtestable** on free
data (base technicals + SEC EDGAR). Congress / analyst / options / insider / short-interest /
revisions / AI signals can only ever be proven **forward**, via the live scorecard ledger.
Never describe those as backtest-proven.

---

## Current live state — verify, don't assume

Read `config/watchlist.yaml` before describing behaviour. As of 2026-08-13:

| Flag | State | Why |
|---|---|---|
| `adds_paused` | **true** | BUY calls withheld pending validation. The sell side (exits/trims on open positions) stays fully live; candidates are still scored and shown. |
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

# Run the tests — 570 tests, ~36s
./.venv/Scripts/python.exe -m pytest -q

# Regime-overlay validation gate
python -m src.backtest --regime
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

---

## Rules for Claude

1. **Never claim this beats the market.** See the finding above. State the drawdown/idea-surface
   value instead.
2. **Use TDD** — this project is test-driven (570 tests). Write the failing test first
   (`superpowers:test-driven-development`).
3. **Verify live config before describing behaviour** — flags have been flipped both ways.
4. **Always explain commands** before running them; the owner is a beginner.
5. **No shortcuts, no bandaids** — do it properly or flag it and ask.
6. Never weaken a test to make it pass.
