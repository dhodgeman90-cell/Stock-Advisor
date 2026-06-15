# Stock Advisor

Local, free tool that scans a watchlist and prints/emails a ranked list of
short-term momentum buy candidates. **Suggests only — never trades.**

> **Profile-aware engine:** `main.run()` accepts a `Profile` (config/data/reports
> dirs + secret source). With no argument it uses `Profile.for_repo()` — the owner's
> repo files and `.env` — so `python -m src.main` is unchanged. A packaged per-user
> build passes `Profile.for_base(<%APPDATA%/StockAdvisor>)` instead, keeping each
> person's data isolated from the program files. See
> `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md`.

See the design spec in `docs/superpowers/specs/` for the full picture.

## Phase 1 (this build): deterministic core

### Setup (one time)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run
```powershell
python -m src.main      # scan the watchlist, print + save a ranked report
```

### Test
```powershell
pytest -v
```

---

## Phase 3: holdings tracking, exit signals, and backtesting

### Holdings & exit signals

You can track holdings two ways — pick one:

#### Option A — Automatic sync from Robinhood (recommended)

Connect your Robinhood account once through **SnapTrade** (a sanctioned brokerage-data
API) and every briefing pulls your live holdings *and your real average cost* automatically
— no more hand-editing files, no inaccurate back-calculated entry prices.

**Why SnapTrade and not a Robinhood password?** Robinhood has no official API. SnapTrade
handles the login + 2FA **once** at connection time and stores scoped tokens instead of your
password, so the unattended 7 AM briefing never gets stuck waiting for a 2FA code. Free tier
covers one user with up to five brokerage connections — fine for personal use.

**One-time setup (~15 min):**

1. Create a free account at <https://snaptrade.com>, make an app, and copy its
   `clientId` + `consumerKey` into `.env` as `SNAPTRADE_CLIENT_ID` / `SNAPTRADE_CONSUMER_KEY`.
2. Run the linker and follow the prompts:
   ```powershell
   & .\.venv\Scripts\python.exe -m src.link_broker
   ```
   It registers you, prints a `SNAPTRADE_USER_SECRET` to paste into `.env`, then opens a
   browser so you can log into Robinhood and approve access. It finishes by confirming the
   holdings it detected.
3. Done. Holdings now refresh automatically before every briefing.

If SnapTrade is ever unreachable, the briefing automatically falls back to `positions.yaml`
(below), so your morning email never breaks.

#### Option B — Manual `positions.yaml`

If you don't connect SnapTrade, track holdings by editing `config/positions.yaml`.

**Minimum required fields:** `ticker` and `entry_price`.
**Optional fields:** `entry_date`, `shares`, and per-position threshold overrides
`stop_loss_pct` / `take_profit_pct` (these override the defaults in `exits.yaml`).
Use `positions: []` when you hold nothing.

> **When SnapTrade is connected**, `positions.yaml` becomes an optional *overrides* file:
> SnapTrade supplies the live ticker/shares/cost basis, and any `stop_loss_pct`,
> `take_profit_pct`, `trailing_stop_pct`, or `entry_date` you list for a ticker is merged on
> top. You can blank it to `positions: []` so your real holdings aren't committed to git.

```yaml
# config/positions.yaml
positions:
  - ticker: NVDA
    entry_price: 120.50
    entry_date: 2026-06-01
    shares: 2
    stop_loss_pct: 10      # optional — overrides the exits.yaml default
    take_profit_pct: 25    # optional — overrides the exits.yaml default
```

When you run the daily briefing, the very first section is **"Your holdings"**,
showing each position's current price, percentage from your entry, and any exit signals.

**Exit signal key:**

| Emoji | Meaning | Trigger |
|-------|---------|---------|
| 🔴 | Sell | Stop-loss hit (price fell past your floor), or price closed below the 50-day MA |
| 🟢 | Take profit (trim/sell) | Target gain reached |
| 🟡 | Watch / trim | Price slipped below the 20-day MA, or momentum fading on drying volume |

Exit signals are **deterministic** — they are calculated from price and volume data
alone. The AI Risk agent may add an optional ⚠️ annotation with context, but it
never overrides or drives the exit decision.

**Tuning the thresholds** — all defaults live in the `defaults` section of
`config/exits.yaml`:

| Key | What it controls |
|-----|-----------------|
| `stop_loss_pct` | Sell if price drops this % below entry |
| `take_profit_pct` | Trim/sell if price rises this % above entry |
| `trend_break_fast` | MA window (days) for the 🟡 watch signal |
| `trend_break_slow` | MA window (days) for the 🔴 trend-break sell signal |
| `momentum_fade` | RSI + volume thresholds for the 🟡 momentum-fade signal |

### Backtesting

```powershell
& .\.venv\Scripts\python.exe -m src.backtest
```

The backtester replays the same deterministic scoring and exit engine over
`window_years` of price history (set in the `backtest` section of `config/exits.yaml`),
trade by trade. There are **no AI calls** — so it costs nothing and runs in seconds.

Entries are simulated when the base score hits `buy_threshold`; the buy executes at
the **next day's open** so there is no look-ahead bias. Exits follow the same rules
as live signals.

The report covers:

- Trade count, win rate, and average gain vs average loss
- Average hold time (trading days)
- Strategy total return vs an equal-weight buy-and-hold baseline across the watchlist
- A per-trade list with entry/exit dates, return %, and exit reason

Results are saved to `reports/backtest-YYYY-MM-DD.md` and also printed to the terminal.

> **Honest caveat:** a good backtest result is encouraging, but not a guarantee.
> Overfitting is a real risk — the same data used to tune thresholds will look
> flattering in hindsight. Treat results skeptically and confirm with paper trading
> before risking real money.

---

## Automation (Phase 4) — hands-off daily briefing

Run the briefing automatically every weekday at 7:00 AM and email it to yourself.

### 1. Set up email (one time)

The briefing emails itself whenever `EMAIL_*` are set in `.env`.

1. Turn on 2-Step Verification for your Google account.
2. Create a Gmail **App Password**: Google Account -> Security -> 2-Step
   Verification -> App passwords. Name it "Stock Advisor". Copy the 16-character
   password.
3. In `.env`, set:
   - `EMAIL_USER` = your Gmail address
   - `EMAIL_PASSWORD` = the 16-character App Password (not your normal password)
   - `EMAIL_TO` = where to send it (your own address is fine)
   (`EMAIL_HOST`/`EMAIL_PORT` already default to Gmail's SSL settings.)

> To send to more than one person later, make `EMAIL_TO` a comma-separated list.
> (Private Bcc sharing is a small future addition.)

### 2. Verify email by hand BEFORE scheduling

```powershell
& .\.venv\Scripts\python.exe -m src.main
```

Confirm the briefing lands in your inbox. Only continue once it does.

### 3. Schedule it

Preview first, then register:

```powershell
.\scripts\setup-schedule.ps1 -WhatIf    # preview — creates nothing
.\scripts\setup-schedule.ps1            # actually register the task
```

If it warns that wake timers are off, follow the printed `powercfg` fix (or ignore
it — the task still runs the next time you turn the PC on).

### 4. Test the task without waiting for 7:00 AM

```powershell
Start-ScheduledTask -TaskName StockAdvisorDailyBriefing
Get-Content (".\logs\briefing-{0:yyyy-MM-dd}.log" -f (Get-Date)) -Tail 20
```

You should see the run logged and the email arrive.

### Manage it

```powershell
Get-ScheduledTask     -TaskName StockAdvisorDailyBriefing   # see it / its state
Get-ScheduledTaskInfo -TaskName StockAdvisorDailyBriefing   # last run time + result
.\scripts\remove-schedule.ps1                               # stop automation
```
