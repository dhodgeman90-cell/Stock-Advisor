# Stock Advisor

Local, free tool that scans a watchlist and prints/emails a ranked list of
short-term momentum buy candidates. **Suggests only — never trades.**

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

Edit `config/positions.yaml` to track what you own. The file is checked in to the
repo so it stays with your other settings — update it whenever you buy or sell.

**Minimum required fields:** `ticker` and `entry_price`.
**Optional fields:** `entry_date`, `shares`, and per-position threshold overrides
`stop_loss_pct` / `take_profit_pct` (these override the defaults in `exits.yaml`).
Use `positions: []` when you hold nothing.

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
