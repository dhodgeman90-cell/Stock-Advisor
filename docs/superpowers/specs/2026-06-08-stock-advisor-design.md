# Stock Advisor — Design Spec

**Date:** 2026-06-08
**Status:** Design approved; pending spec review → implementation plan
**Owner skill level:** Beginner — every command must be explained before running

---

## 1. Overview

A personal, local Python tool that produces a **daily morning briefing** of stock
buy candidates and sell signals for a small, self-directed Robinhood account
(~$280). Inspired by Lewis Jackson's "7 AI agents" SEC-monitoring setup, but
re-scoped for short-term momentum trading.

**It suggests; it never trades.** No brokerage connection, no order execution.
The user reads the briefing and makes every decision manually.

### Primary goals (all of these, per the user)
- Build a real, understandable, extensible agentic pipeline (the craft is the prize).
- Treat the $280 account as a genuine live testbed where good calls matter.
- Optimize for signal quality.
- Prove whether a setup like this can realistically produce useful daily picks.

### Honest framing
- At $280, financial upside is small; the **system + learning** is the real value.
- An LLM is not a financial advisor. This is an **information funnel**, not a money button.
- Most simple strategies show no real edge — backtesting exists to find that out **for free**.

---

## 2. Architecture (chosen approach: "B+")

A deterministic core with a small crew of **bounded** specialist AI agents.
**Math decides the ranking; agents inform and annotate within capped authority.**

```
  6:30am ET  Windows Task Scheduler fires the script
      │
      ▼
  1. LOAD      watchlist.yaml, weights.yaml, positions.yaml, config
      ▼
  2. EXITS     evaluate sell signals on current holdings  (Section 7)
      ▼
  3. FETCH     pull + cache + validate price/volume for watchlist  (Section 3)
      ▼
  4. SCORE     deterministic 0-100 score per ticker (logic gates)  (Section 4)
      ▼
  5. SHORTLIST keep top N (default 8) for the agents
      ▼
  6. AGENTS    News / Risk / Context crew → structured verdicts  (Section 5)
      ▼
  7. ADJUDICATE combine scores + verdicts, capped boosts/vetoes  (Section 6)
      ▼
  8. BRIEFING  build + email + save dated report  (Section 6)
      ▼
  9. LOG       persist run inputs/scores/picks for audit + backtest
```

### Why B+ (vs. pure rules or fully agentic)
- Numbers stay honest and **backtestable** (deterministic base score).
- Delivers the multi-agent "crew" experience without letting an LLM fabricate trades.
- Hallucination is contained: agents nudge/veto within caps; they cannot invent signals.
- Each agent is an isolated, testable unit — and the slot where future agents plug in.

### Design principles
- Deterministic-first, AI-second (AI runs only on a pre-filtered shortlist → cheap, fast).
- Everything logged (audit + backtest fuel).
- Graceful failure: any data/agent/email failure → error notice, never silent, never fabricated.
- Modular "plug" interface so insider (Form 4) + congressional-disclosure agents snap in later.

---

## 3. Watchlist & data layer

- **`watchlist.yaml`** — user-editable list of 20-50 liquid tickers + settings
  (`shortlist_size: 8`, `lookback_days: 200`).
- **Data source:** free library (yfinance, Stooq fallback). **End-of-day** daily
  OHLCV — correct basis for next-morning swing-trade decisions. Intraday/real-time
  is a future paid upgrade, not needed now.
- **Caching:** each run saves fetched data to `data/`; avoids rate-limiting and
  allows a clearly-flagged stale-data fallback if the source is down.
- **Quality guardrails:** drop tickers with missing days, no-trade, or bad/zero
  prices — with a note in the briefing rather than poisoning a score.

Output: clean, validated per-ticker price/volume history for the scoring engine.

---

## 4. Deterministic scoring engine (the "logic gates")

Pure math, no AI. Each ticker → a single **0-100 score**.

### Signals
| Signal | Measures | Example rule |
|---|---|---|
| Trend | Uptrend? | Price > 50-day MA; 20-day MA > 50-day MA |
| Momentum (RSI) | Strength without overheating | RSI ~50-70 healthy; >80 penalized |
| Breakout | New short-term highs? | Price near/above 20-day high |
| Volume | Conviction behind the move | Volume > 1.5× 20-day average |
| Pullback quality | Buyable dip vs. falling knife | Above longer trend but recently dipped |

### Combination — weighted score (chosen tilt: **momentum / breakout chaser**)
```yaml
weights:
  breakout: 30
  volume: 30
  momentum: 20
  trend: 15
  pullback: 5
```
Weights live in `weights.yaml` and are tunable. **Implication of this tilt:** more
signals and more false positives → the **Risk agent is the critical counterweight.**

### Hard filters (true gates — override the score)
- **Liquidity floor** — exclude illiquid names (hard to sell). No exceptions.
- **Price floor** — exclude sub-$X penny junk.
- **Data-valid** — must pass Section 3 checks.

Output: every ticker scored; top `shortlist_size` advance to the agent crew.

---

## 5. Agent crew (bounded specialists)

Run on cheap **Claude Haiku**. Each has one job, a strict structured (JSON)
output contract, and capped authority. On error/timeout/junk → treated as
**"no opinion"** (neutral); never crashes, never invents a signal.

- **🚩 Risk agent** (most important given momentum tilt)
  - Input: ticker, score, recent price action, headlines.
  - Job: reasons NOT to buy — pump-and-dump, earnings within 24-48h (gap risk),
    dilution/offering, halt, lawsuit/fraud probe, spike on no news.
  - Output: `{ risk_level: low|medium|high, red_flags: [...], veto: bool, reason }`
  - Power: demote within cap, or hard **VETO**.
- **📰 News agent**
  - Input: ticker, recent headlines.
  - Job: identify why it's moving — real catalyst vs. hype vs. nothing.
  - Output: `{ catalyst: bool, catalyst_type, sentiment: pos|neutral|neg, summary }`
  - Power: boost (real catalyst) or demote (hype/nothing) within cap.
- **🧭 Context agent** (once per day, not per stock — Lewis's "Frank")
  - Input: broad market indicators.
  - Job: set the day's regime (risk-on/neutral/risk-off).
  - Output: `{ regime: risk_on|neutral|risk_off, note }`
  - Power: small global adjustment to all scores.

The structured contract is the **plug** where insider (Form 4) and congressional
agents attach later.

---

## 6. Adjudicator + daily briefing

### Adjudicator (the referee — mostly rules)
```
final_score = base_score
if news.catalyst:          final_score += boost   (capped, e.g. +15)
if news.sentiment == neg:  final_score -= demote  (capped)
if risk.risk_level high:   final_score -= demote  (capped, e.g. -20)
apply context regime adjustment (global, small)
if risk.veto:              EXCLUDE → show in "vetoed" section
rank by final_score
```
Hard rules: **veto always wins**; all boosts/demotes **clamped** to caps; the
base (math) score is **always shown** beside the final score.

### Briefing (email + dated saved report)
- Leads with **holdings/exit signals** (Section 7), then **new candidates**.
- Each item shows full reasoning (the "why"), not just a number.
- Vetoed stocks shown with reason (transparency over black box).
- Failed run → emails an error notice (never silence).
- Disclaimer footer every time (information, not advice).
- Same content saved to `reports/YYYY-MM-DD.md` → history + backtest fuel.

---

## 7. Positions & exit signals (the sell side)

The user updates **`positions.yaml`** when they buy/sell (chosen: **manual file** —
no Robinhood auto-sync, which is unofficial, against ToS, and a security/account
risk). Each morning, before scanning for buys, the system evaluates holdings:

| Exit signal | Result |
|---|---|
| Stop-loss (price fell X% below entry) | 🔴 SELL |
| Take-profit (hit target gain) | 🟢 TRIM/SELL |
| Trend break (below moving average) | 🟡 SELL signal |
| Momentum fading (RSI rolling over, volume drying up) | 🟡 watch/trim |
| Risk-agent veto on a held name (e.g. earnings incoming) | ⚠️ consider exit |

Briefing reminder: prompt the user to keep `positions.yaml` current.

---

## 8. Backtesting & safety

### Backtesting (proof before risking money)
Replay the deterministic engine on 1-2 years of history. Measure: win rate,
avg gain vs. avg loss, exit-rule performance, and **comparison to buy-and-hold**.
If results ≈ coin flip, we learn it **for free** and tune or abandon.

**Caveat (real, not a bandaid):** a good backtest is encouraging, not a guarantee;
overfitting is a genuine risk. Build to avoid common traps; treat results skeptically.

### Safety rails
| Rail | Effect |
|---|---|
| Never trades | Suggests only; no brokerage link, no orders |
| $5/month spend cap | Set in Anthropic Console (user setup step) — hard cost ceiling |
| Kill switch | Disable scheduled task → everything stops, $0 |
| Graceful failure | Any failure → error notice; never silent/fabricated |
| Everything logged | Audit any past call; feeds backtests |
| Disclaimers | Every briefing: information, not advice |
| Paper-trading period | Run live, track picks WITHOUT real money for a few weeks before committing $280 |

**Recommended rollout sequence:** backtest (free) → paper-trade (a few weeks) → real money.

---

## 9. Project structure & tech stack

```
stock-advisor/
├── README.md
├── requirements.txt
├── .env                       ← API key + email password (git-ignored)
├── .gitignore
├── config/
│   ├── watchlist.yaml
│   ├── weights.yaml
│   └── positions.yaml
├── src/
│   ├── main.py                ← conductor: runs the daily pipeline in order
│   ├── data.py                ← fetch + cache + validate (Section 3)
│   ├── scoring.py             ← deterministic engine (Section 4)
│   ├── agents.py              ← News/Risk/Context crew (Section 5)
│   ├── adjudicator.py         ← combine scores + verdicts (Section 6)
│   ├── exits.py               ← sell-side logic (Section 7)
│   ├── briefing.py            ← build/send email + save report (Section 6)
│   └── backtest.py            ← replay engine on history (Section 8)
├── data/                      ← cached price data (git-ignored)
├── reports/                   ← dated briefings (git-ignored)
└── logs/                      ← run logs
```

### Tech stack (all free except the capped API)
| Piece | Tool |
|---|---|
| Language | Python |
| Market data | yfinance (Stooq fallback) |
| Calculations | pandas |
| Agents | Anthropic API — Claude Haiku (~$4/mo, capped at $5) |
| News | free RSS/news feeds |
| Email | smtplib (built-in) + Gmail |
| Scheduling | Windows Task Scheduler |
| Config | YAML |
| Secrets | .env (git-ignored) |

### Costs (where money is incurred)
- **Only** the agent LLM calls cost money. Everything else is $0.
- ~18 short Haiku calls/day ≈ **~$0.13/day ≈ ~$4/month**; lower with prompt caching.
- Pay-as-you-go, **no subscription**: stop running the script → charges stop, $0.
  Separate from any Claude.ai/Claude Code plan (own API key, own billing).
- **$5/month hard cap** set in Anthropic Console; preload a small credit balance.
- $0 alternatives if desired: local open-source model (Ollama), or pure-rules (no agents).

### Run commands
```powershell
python src/main.py        # daily run (Task Scheduler triggers this each morning)
python src/backtest.py    # test the strategy on history anytime
```

### Beginner guarantees
- Every command explained before running.
- Secrets never touch git (`.env` and `data/` git-ignored from day one).

---

## Open items for build phase
- Exact thresholds/caps (stop-loss %, take-profit %, boost/demote caps, liquidity & price floors).
- Initial watchlist contents (chosen together).
- News feed source selection.
- Anthropic Console account + API key + $5 cap (user setup step, walked through).
- Gmail app-password setup for email (user setup step, walked through).
- Model choice confirmation (default Haiku) and exact `claude-haiku-4-5` model id at build time.
