# Stock Advisor — Backtest & Exit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Stock Advisor backtest trustworthy and reproducible (honest window, costs, reporting, offline fallback) and let the strategy keep its winners via a trailing-stop exit.

**Architecture:** All exit behavior flows through the shared `exits.evaluate_exit`, used by both live (`main.py`) and replay (`backtest.simulate_ticker`), so the two never diverge. Code defaults preserve current behavior ("hard" take-profit, zero cost) so the existing 61 tests stay valid; production config files flip the new behavior on. New behavior is added test-first.

**Tech Stack:** Python 3, pandas, yfinance, PyYAML, pytest. Run from `C:\VS Code\Stock Advisor` using `.\.venv\Scripts\python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-08-stock-advisor-backtest-hardening-design.md`

**Branch:** `backtest-hardening` (already created off `master`).

---

## File map

| File | Responsibility | Change |
|------|----------------|--------|
| `src/exits.py` | Shared deterministic exit signals | Add trailing-stop mode (Task 1) |
| `src/backtest.py` | Historical replay + reporting | Peak tracking + costs (Task 2), honest metrics (Task 3), offline loader + `run()` rewrite (Tasks 5, 7) |
| `src/data.py` | Price fetch + cache | Deterministic date-window fetch (Task 4) |
| `src/config.py` | YAML loaders | Parametrized watchlist + positions trailing override (Task 6) |
| `src/main.py` | Live daily pipeline | Pass peak-since-entry into exits (Task 8) |
| `config/exits.yaml` | Exit/backtest knobs | Add mode/trailing/cost (Task 7) |
| `config/watchlist_broad.yaml` | Broad validation universe | New file (Task 6) |
| `tests/test_*.py` | pytest suite | New tests per task |

A full run of the suite is `.\.venv\Scripts\python.exe -m pytest -q` (expected baseline: `61 passed`).

---

## Task 1: Trailing-stop exit mode in `exits.py`

**Files:**
- Modify: `src/exits.py` (the take-profit block, ~lines 28-54)
- Test: `tests/test_exits.py`

Code defaults to `take_profit_mode="hard"` so the existing exits tests (whose `RULES` have no mode key) keep passing unchanged. Trailing mode is opt-in via config.

- [ ] **Step 1: Write failing tests for trailing mode**

Append to `tests/test_exits.py`:

```python
TRAIL_RULES = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "take_profit_mode": "trailing",
        "trailing_stop_pct": 15,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {},
}


def test_trailing_stop_fires_on_pullback_from_peak():
    # Price well above entry and above MAs, but 15%+ below the peak we pass in.
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 70.0, "peak_price": 130.0}
    # 109 is ~16% below peak 130 -> trailing stop fires; not below MAs, not -8% from entry
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" in _types(result)
    assert "take_profit" not in _types(result)               # hard target suppressed in trailing mode


def test_trailing_stop_silent_while_near_peak():
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 70.0, "peak_price": 110.0}
    # 109 is <1% below peak 110 -> no trailing stop
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" not in _types(result)


def test_trailing_mode_still_honors_hard_stop_loss():
    # Steady uptrend, bought too high -> -8% stop must still fire even in trailing mode.
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 119.0, "peak_price": 119.0}
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "stop_loss" in _types(result)


def test_trailing_stop_falls_back_to_entry_when_no_peak_given():
    df = make_df(list(range(50, 110)))                       # last close = 109
    position = {"ticker": "T", "entry_price": 100.0}         # no peak_price; 109 > entry
    # peak falls back to max(entry, price)=109; 109 not 15% below 109 -> no trailing stop, no crash
    result = exits.evaluate_exit(df, position, TRAIL_RULES)
    assert "trailing_stop" not in _types(result)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_exits.py -q`
Expected: FAIL (`trailing_stop` never appears; `KeyError`/`AssertionError`).

- [ ] **Step 3: Implement trailing mode in `evaluate_exit`**

In `src/exits.py`, replace the resolution + take-profit block. Currently lines 28-29 resolve both `stop_pct` and `target_pct`, and lines 50-54 emit `take_profit`. Change to resolve `target_pct` lazily and branch on mode.

Replace:
```python
    stop_pct = float(_resolve(position, defaults, "stop_loss_pct"))
    target_pct = float(_resolve(position, defaults, "take_profit_pct"))
```
with:
```python
    stop_pct = float(_resolve(position, defaults, "stop_loss_pct"))
    mode = str(defaults.get("take_profit_mode", "hard")).lower()
```

Replace the take-profit signal block:
```python
    if price >= entry * (1 + target_pct / 100):
        signals.append({
            "type": "take_profit", "level": "trim", "emoji": "🟢",
            "detail": f"up {pct_from_entry:.1f}% from entry (target +{target_pct:.0f}%)",
        })
```
with:
```python
    if mode == "trailing":
        peak = max(float(position.get("peak_price") or entry), price)
        trail_pct = float(_resolve(position, defaults, "trailing_stop_pct"))
        if peak > 0 and price <= peak * (1 - trail_pct / 100):
            signals.append({
                "type": "trailing_stop", "level": "sell", "emoji": "🔴",
                "detail": (f"down {(price - peak) / peak * 100:.1f}% from peak "
                           f"${peak:.2f} (trail -{trail_pct:.0f}%)"),
            })
    else:
        target_pct = float(_resolve(position, defaults, "take_profit_pct"))
        if price >= entry * (1 + target_pct / 100):
            signals.append({
                "type": "take_profit", "level": "trim", "emoji": "🟢",
                "detail": f"up {pct_from_entry:.1f}% from entry (target +{target_pct:.0f}%)",
            })
```

- [ ] **Step 4: Run exits tests to verify all pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_exits.py -q`
Expected: PASS (old + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/exits.py tests/test_exits.py
git commit -m "feat(exits): add trailing-stop take-profit mode"
```

---

## Task 2: Peak tracking + transaction costs in `simulate_ticker`

**Files:**
- Modify: `src/backtest.py` (`simulate_ticker`, add `_net_return` helper)
- Test: `tests/test_backtest.py`

Existing backtest tests use `RULES_ENTER_ALWAYS` (no `cost_pct_per_side` → defaults to 0, no `take_profit_mode` → hard), so they keep passing.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_backtest.py`:

```python
RULES_TRAILING = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "take_profit_mode": "trailing",
        "trailing_stop_pct": 15,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {"buy_threshold": 0, "max_hold_days": 600},
}


def test_simulate_ticker_lets_winner_run_then_trailing_stops():
    # 62 flat days (entry triggers), climb to 200, then fall 16% off the peak.
    prices = [100.0] * 62 + list(range(100, 201, 5)) + [184.0, 168.0]
    df = make_df([float(p) for p in prices])
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, RULES_TRAILING)
    assert len(trades) == 1
    assert trades[0]["reason"] == "trailing_stop"
    assert trades[0]["return_pct"] > 20.0          # rode well past the old +20% cap


def test_transaction_cost_reduces_return():
    prices = [100.0] * 62 + [92.0]                 # -8% stop, hard mode
    df = make_df(prices)
    df.loc[df.index[61], "Open"] = 100.0           # entry at 100 for clean math
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 60, "cost_pct_per_side": 0.5}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    raw = (92.0 - 100.0) / 100.0 * 100             # -8.0
    assert round(trades[0]["return_pct"], 2) == round(raw - 1.0, 2)   # minus 2*0.5% round-trip


def test_zero_cost_matches_raw_return():
    prices = [100.0] * 62 + [92.0]
    df = make_df(prices)
    df.loc[df.index[61], "Open"] = 100.0
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 0, "max_hold_days": 60, "cost_pct_per_side": 0.0}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert round(trades[0]["return_pct"], 2) == -8.0
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: FAIL (no trailing exit; cost not applied).

- [ ] **Step 3: Add `_net_return` helper and wire peak + cost into `simulate_ticker`**

In `src/backtest.py`, add the helper above `simulate_ticker`:

```python
def _net_return(entry_price, exit_price, rules) -> float:
    """Trade return (%) after a round-trip transaction cost."""
    raw = (exit_price - entry_price) / entry_price * 100
    cost = 2 * float(rules["backtest"].get("cost_pct_per_side", 0.0))
    return raw - cost
```

In `simulate_ticker`, when opening a trade, seed a peak. Change the `open_trade = {...}` assignment to include `"peak": float(df["Open"].iloc[entry_idx])`:

```python
                open_trade = {
                    "entry_idx": entry_idx,
                    "entry_price": float(df["Open"].iloc[entry_idx]),
                    "entry_date": df.index[entry_idx],
                    "peak": float(df["Open"].iloc[entry_idx]),
                }
```

In the `else:` (open-trade) branch, update the peak and pass it into the position, replacing the existing `position = {...}` and `ret = ...` lines:

```python
        else:
            open_trade["peak"] = max(open_trade["peak"], float(df["Close"].iloc[i]))
            position = {"ticker": ticker, "entry_price": open_trade["entry_price"],
                        "peak_price": open_trade["peak"]}
            ev = exits.evaluate_exit(window, position, rules)
            held_days = i - open_trade["entry_idx"]
            signalled = any(s["level"] in _EXIT_LEVELS for s in ev["signals"])
            force = held_days >= max_hold
            if signalled or force:
                exit_price = float(df["Close"].iloc[i])
                reason = (next(s["type"] for s in ev["signals"] if s["level"] in _EXIT_LEVELS)
                          if signalled else "max_hold")
                ret = _net_return(open_trade["entry_price"], exit_price, rules)
```

In the end-of-data force-close block, replace its `ret = ...` line with:
```python
        ret = _net_return(open_trade["entry_price"], exit_price, rules)
```

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: PASS (old + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): track peak for trailing stop and apply transaction cost"
```

---

## Task 3: Honest, apples-to-apples reporting

**Files:**
- Modify: `src/backtest.py` (`summarize`, new `compounded_per_name`, `render_backtest_report`)
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_backtest.py`:

```python
def test_compounded_per_name_compounds_then_averages():
    trades = [
        {"ticker": "A", "return_pct": 10.0},   # A: 1.10 * 1.10 = 1.21 -> +21%
        {"ticker": "A", "return_pct": 10.0},
        {"ticker": "B", "return_pct": -50.0},  # B: -50%
    ]
    # average of +21% and -50% = -14.5%
    assert round(backtest.compounded_per_name(trades), 1) == -14.5


def test_compounded_per_name_empty():
    assert backtest.compounded_per_name([]) == 0.0


def test_summarize_includes_expectancy():
    trades = [
        {"return_pct": 20.0, "hold_days": 10, "reason": "take_profit"},
        {"return_pct": -8.0, "hold_days": 3, "reason": "stop_loss"},
    ]
    s = backtest.summarize(trades)
    # 0.5*20 + 0.5*(-8) = 6.0
    assert round(s["expectancy"], 1) == 6.0


def test_report_drops_misleading_sum_and_shows_compounded():
    trades = [{"ticker": "AAA", "entry_date": "2024-01-01", "exit_date": "2024-01-05",
               "entry_price": 100.0, "exit_price": 108.0, "return_pct": 8.0,
               "hold_days": 4, "reason": "trailing_stop"}]
    summary = backtest.summarize(trades)
    text = backtest.render_backtest_report(summary, 5.0, trades, "2026-06-08")
    assert "Sum of all" not in text                       # misleading headline removed
    assert "compounded" in text.lower()
    assert "Expectancy" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: FAIL (`compounded_per_name` undefined; no `expectancy`; sum line still present).

- [ ] **Step 3: Implement metrics + restructure report**

In `src/backtest.py`, add after `summarize`:

```python
def compounded_per_name(trades) -> float:
    """Per-ticker sequential trades compound; average the result across tickers (%).

    Comparable to per-name buy-and-hold because each ticker holds one trade at a time.
    """
    factors = {}
    for t in trades:
        factors[t["ticker"]] = factors.get(t["ticker"], 1.0) * (1 + t["return_pct"] / 100)
    if not factors:
        return 0.0
    rets = [(f - 1) * 100 for f in factors.values()]
    return sum(rets) / len(rets)
```

In `summarize`, add `expectancy` to BOTH return dicts. In the empty-trades return add `"expectancy": 0.0,`. In the populated return add:
```python
        "expectancy": (len(wins) / len(trades)) * ((sum(wins) / len(wins)) if wins else 0.0)
                      + (len(losses) / len(trades)) * ((sum(losses) / len(losses)) if losses else 0.0),
```

Replace `render_backtest_report` with the new signature and body (keeps the strings the older test asserts: "Avg return per trade", "Buy-and-hold baseline", "not financial advice"):

```python
def render_backtest_report(summary, baseline, trades, date_str, label="default", sources=None) -> str:
    compounded = compounded_per_name(trades)
    L = [
        f"# Stock Advisor — Backtest ({label}, {date_str})",
        "",
        f"- Trades: **{summary['count']}**",
        f"- Win rate: **{summary['win_rate']:.0f}%**",
        f"- Avg gain: **{summary['avg_gain']:+.1f}%**  |  Avg loss: **{summary['avg_loss']:+.1f}%**",
        f"- Expectancy per trade: **{summary['expectancy']:+.1f}%**",
        f"- Avg hold: **{summary['avg_hold']:.0f}** trading days",
        "",
        "### Strategy vs buy-and-hold (per name, comparable)",
        f"- Strategy return per name (compounded): **{compounded:+.1f}%**",
        f"- Buy-and-hold baseline (avg per watchlist name): **{baseline:+.1f}%**",
        f"- Avg return per trade: **{summary['avg_trade_return']:+.1f}%**",
        "",
        "## Exit reasons",
    ]
    if summary["by_reason"]:
        for reason, count in summary["by_reason"].most_common():
            L.append(f"- {reason.replace('_', ' ')}: {count}")
    else:
        L.append("_No trades._")
    if sources:
        from collections import Counter as _C
        tally = _C(sources.values())
        L.append("")
        L.append("## Data sources")
        for src, n in tally.most_common():
            L.append(f"- {src}: {n} tickers")
    L.append("")
    L.append("## Trades")
    if trades:
        for t in trades:
            L.append(
                f"- {t['ticker']} {t['entry_date']} → {t['exit_date']} "
                f"({t['hold_days']}d): {t['return_pct']:+.1f}% "
                f"[{t['reason'].replace('_', ' ')}]"
            )
    else:
        L.append("_No trades._")
    L.append("")
    L.append("> Caveat: a good backtest is encouraging, not a guarantee. Overfitting is a "
             "real risk — treat these numbers skeptically and confirm with paper trading.")
    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"
```

- [ ] **Step 4: Run full suite to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all, including the older `test_render_backtest_report_lists_trades_and_baseline`).

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): honest compounded-per-name + expectancy reporting"
```

---

## Task 4: Deterministic price window in `data.py`

**Files:**
- Modify: `src/data.py` (`fetch_history`, add `_window_bounds`, `WARMUP_DAYS`)
- Test: `tests/test_data.py`

- [ ] **Step 1: Write failing test for the pure bounds helper**

Append to `tests/test_data.py`:

```python
import datetime as dt
from src import data as data_mod


def test_window_bounds_honors_days_plus_warmup():
    today = dt.date(2026, 6, 8)
    start, end = data_mod._window_bounds(730, today=today, warmup=100)
    assert start == "2024-02-29"          # 2026-06-08 minus 830 days (730 + 100 warmup)
    assert end == "2026-06-09"            # today + 1 day (yfinance end is exclusive)
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_data.py -q`
Expected: FAIL (`_window_bounds` undefined).

- [ ] **Step 3: Implement deterministic window**

In `src/data.py`, add at top (after `import pandas as pd`):

```python
import datetime as dt

WARMUP_DAYS = 100   # extra calendar days so the SMA-50 / MIN_HISTORY ramp is warm
```

Add the helper:

```python
def _window_bounds(days, today=None, warmup=WARMUP_DAYS):
    """Return (start_iso, end_iso) for an explicit yfinance date range.

    end is exclusive (yfinance convention) so we add one day to include today.
    """
    today = today or dt.date.today()
    start = today - dt.timedelta(days=int(days) + int(warmup))
    end = today + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()
```

Replace `fetch_history` body:

```python
def fetch_history(ticker: str, days: int):
    """Download daily OHLCV from yfinance over an explicit date window.

    Network call — not used in tests. The window is days + WARMUP_DAYS calendar
    days so the requested `days` span is fully usable after indicator warm-up.
    """
    import yfinance as yf

    start, end = _window_bounds(days)
    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df
```

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_data.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data.py tests/test_data.py
git commit -m "fix(data): honor window via explicit date range, drop 1.6x fudge"
```

---

## Task 5: Offline-resilient ticker loader in `backtest.py`

**Files:**
- Modify: `src/backtest.py` (add `_load_history`)
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write failing tests (monkeypatched, no network)**

Append to `tests/test_backtest.py`:

```python
from src import data as _data


def test_load_history_uses_cache_when_fetch_fails(monkeypatch, tmp_path):
    good = make_df([100.0] * 60)
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: (_ for _ in ()).throw(RuntimeError("net down")))
    monkeypatch.setattr(_data, "load_cache", lambda t, dd: good)
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "cache"
    assert df is not None


def test_load_history_skips_when_no_data_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: None)
    monkeypatch.setattr(_data, "load_cache", lambda t, dd: None)
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "skipped"
    assert df is None


def test_load_history_saves_cache_on_live_success(monkeypatch, tmp_path):
    good = make_df([100.0] * 60)
    saved = {}
    monkeypatch.setattr(_data, "fetch_history", lambda t, d: good)
    monkeypatch.setattr(_data, "save_cache", lambda df, t, dd: saved.update({t: True}))
    df, source = backtest._load_history("T", 730, tmp_path)
    assert source == "live"
    assert saved.get("T") is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: FAIL (`_load_history` undefined).

- [ ] **Step 3: Implement the loader**

In `src/backtest.py`, add (near the top, after the imports/constants):

```python
def _load_history(ticker, days, data_dir):
    """Return (df_or_None, source). Tries live fetch, falls back to cache.

    source is 'live', 'cache', or 'skipped'. Never raises on a bad fetch.
    """
    try:
        df = data.fetch_history(ticker, days)
    except Exception:
        df = None
    if df is not None and data.validate(df, ticker)[0]:
        data.save_cache(df, ticker, data_dir)
        return df, "live"
    cached = data.load_cache(ticker, data_dir)
    if cached is not None and data.validate(cached, ticker)[0]:
        return cached, "cache"
    return None, "skipped"
```

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): offline-resilient per-ticker history loader"
```

---

## Task 6: Parametrized watchlist + positions trailing override + broad universe

**Files:**
- Modify: `src/config.py` (`load_watchlist`, `load_positions`)
- Create: `config/watchlist_broad.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_config.py` (match the file's existing tmp-dir pattern — write YAML to `tmp_path` and pass `config_dir=tmp_path`):

```python
def test_load_watchlist_named_loads_suffixed_file(tmp_path):
    (tmp_path / "watchlist_broad.yaml").write_text(
        "tickers:\n  - JNJ\n  - XOM\nsettings:\n  shortlist_size: 5\n", encoding="utf-8")
    wl = config.load_watchlist("broad", config_dir=tmp_path)
    assert wl["tickers"] == ["JNJ", "XOM"]


def test_load_positions_reads_trailing_stop_override(tmp_path):
    (tmp_path / "positions.yaml").write_text(
        "positions:\n  - ticker: AAA\n    entry_price: 100\n    trailing_stop_pct: 12\n",
        encoding="utf-8")
    pos = config.load_positions(config_dir=tmp_path)
    assert pos[0]["trailing_stop_pct"] == 12
```

(If `tests/test_config.py` imports `config` differently, follow that file's existing import style.)

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL (`load_watchlist` rejects the positional name / no `trailing_stop_pct` key).

- [ ] **Step 3: Implement loader changes**

In `src/config.py`, change `load_watchlist` signature and first line:

```python
def load_watchlist(name=None, config_dir=CONFIG_DIR) -> dict:
    fname = "watchlist.yaml" if name is None else f"watchlist_{name}.yaml"
    data = _load(fname, config_dir)
```
(Keep the rest of the function unchanged.)

In `load_positions`, add the trailing field to the appended dict:
```python
            "stop_loss_pct": p.get("stop_loss_pct"),
            "take_profit_pct": p.get("take_profit_pct"),
            "trailing_stop_pct": p.get("trailing_stop_pct"),
```

- [ ] **Step 4: Create the broad watchlist file**

Create `config/watchlist_broad.yaml`:

```yaml
# Neutral, sector-spread universe for unbiased backtest validation.
# Deliberately includes laggards (INTC, F, VZ, DIS) so it is not cherry-picked.
tickers:
  - JNJ    # healthcare
  - UNH    # health insurance
  - JPM    # banking
  - XOM    # energy
  - PG     # consumer staples
  - KO     # consumer staples
  - CAT    # industrial
  - NEE    # utility
  - VZ     # telecom
  - DIS    # media
  - INTC   # semiconductors (laggard)
  - F      # autos (laggard)
settings:
  shortlist_size: 8
  lookback_days: 200
  min_price: 5.0
  min_avg_volume: 500000
```

- [ ] **Step 5: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config.py config/watchlist_broad.yaml
git commit -m "feat(config): named watchlists, positions trailing override, broad universe"
```

---

## Task 7: Wire `backtest.run()` to watchlist + offline loader + production config

**Files:**
- Modify: `src/backtest.py` (`run`, `__main__`)
- Modify: `config/exits.yaml`

`run()` is orchestration (not unit-tested today); verify by executing it in Task 9.

- [ ] **Step 1: Rewrite `run()` and the CLI entry**

In `src/backtest.py`, replace `run()` and the `__main__` block:

```python
def run(watchlist_name=None) -> str:
    wl = config.load_watchlist(watchlist_name)
    weights = config.load_weights()
    rules = config.load_exit_rules()
    settings = wl["settings"]
    years = int(rules["backtest"]["window_years"])
    days = years * 365
    data_dir = ROOT / "data"

    histories = {}
    all_trades = []
    sources = {}
    for ticker in wl["tickers"]:
        df, source = _load_history(ticker, days, data_dir)
        sources[ticker] = source
        if df is None:
            continue
        histories[ticker] = df
        all_trades.extend(simulate_ticker(df, ticker, weights, settings, rules))

    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str,
                                  label=label, sources=sources)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-{label}-{date_str}.md").write_text(text, encoding="utf-8")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
```

- [ ] **Step 2: Flip production config in `config/exits.yaml`**

Under `defaults:` add `take_profit_mode` and `trailing_stop_pct`; under `backtest:` add `cost_pct_per_side`:

```yaml
defaults:
  stop_loss_pct: 8
  take_profit_pct: 20         # used only when take_profit_mode is 'hard'
  take_profit_mode: trailing  # 'trailing' lets winners run; 'hard' caps at take_profit_pct
  trailing_stop_pct: 15       # sell if price <= peak_since_entry * (1 - 0.15)
  trend_break_fast: 20
  trend_break_slow: 50
  momentum_fade:
    rsi_was_above: 70
    volume_dry_ratio: 0.7
backtest:
  buy_threshold: 65
  max_hold_days: 60
  window_years: 2
  cost_pct_per_side: 0.1      # 0.2% round-trip slippage/commission
  baseline: equal_weight_watchlist
```

- [ ] **Step 3: Run the full suite (no regressions)**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add src/backtest.py config/exits.yaml
git commit -m "feat(backtest): run() supports named watchlists + offline loader; enable trailing+costs"
```

---

## Task 8: Pass peak-since-entry into live exits in `main.py`

**Files:**
- Modify: `src/main.py` (holdings loop, add `import pandas as pd`)

No unit test (main is an untested conductor); verified by a real run in Task 9.

- [ ] **Step 1: Add the pandas import**

In `src/main.py`, add to the imports near the top:
```python
import pandas as pd
```

- [ ] **Step 2: Compute and pass `peak_price` before `evaluate_exit`**

In the holdings loop, replace the final line `holdings.append(exits.evaluate_exit(df, pos, exit_rules))` with:

```python
        entry_date = pos.get("entry_date") or ""
        try:
            if entry_date:
                since = df.loc[df.index >= pd.Timestamp(entry_date)]
                peak = float(since["Close"].max()) if len(since) else float(pos["entry_price"])
            else:
                peak = float(pos["entry_price"])
        except Exception:
            peak = float(pos["entry_price"])
        holdings.append(exits.evaluate_exit(df, {**pos, "peak_price": peak}, exit_rules))
```

- [ ] **Step 3: Verify the live pipeline still renders (no API key path)**

Run: `.\.venv\Scripts\python.exe -m src.main`
Expected: prints a briefing ending with `[AI agents disabled: no ANTHROPIC_API_KEY in .env]` and no traceback. (If `positions.yaml` is empty, the holdings section is empty — that's fine; the run must not crash.)

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat(main): supply peak-since-entry so live exits use the trailing stop"
```

---

## Task 9: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all green (61 original + new tests).

- [ ] **Step 2: Default backtest**

Run: `.\.venv\Scripts\python.exe -m src.backtest`
Expected: console report titled `Backtest (default, <date>)`; contains "Strategy return per name (compounded)", "Expectancy per trade", a "Data sources" section, and trailing_stop among exit reasons; NO "Sum of all" line. File `reports/backtest-default-<date>.md` written.

- [ ] **Step 3: Broad backtest**

Run: `.\.venv\Scripts\python.exe -m src.backtest broad`
Expected: report titled `Backtest (broad, <date>)`; file `reports/backtest-broad-<date>.md` written; runs over the 12 broad tickers.

- [ ] **Step 4: Compare and sanity-check**

Read both report files. Confirm the compounded strategy-per-name vs buy-and-hold lines are present and plausible, exit reasons now include `trailing_stop`, and returns reflect costs. Note the default-watchlist compounded figure vs the old +2.0%/trade as the headline result of the hardening.

- [ ] **Step 5: Final commit (if any report-driven tweaks were needed)**

```bash
git add -A
git commit -m "chore: verification pass for backtest hardening"
```

---

## Self-review notes

- **Spec coverage:** Fix 1 → Task 4; Fix 2 → Tasks 1, 2, 8 + config Task 7; Fix 3 → Task 2 + config Task 7; Fix 4 → Task 3; Fix 5 → Task 6 + run wiring Task 7; Fix 6 → Task 5 + Task 7. Testing section → tests embedded per task. All covered.
- **Backward compatibility:** code defaults (`take_profit_mode="hard"`, `cost_pct_per_side=0.0`) keep the existing 61 tests valid; production behavior is enabled only via `config/exits.yaml` in Task 7.
- **Type/name consistency:** `_load_history` (Task 5) used by `run()` (Task 7); `compounded_per_name`/`expectancy` (Task 3) used by `render_backtest_report` (Task 3) and `run()` (Task 7); `_window_bounds`/`WARMUP_DAYS` (Task 4) used by `fetch_history`; `peak_price` produced in Tasks 2 & 8, consumed in Task 1; `render_backtest_report(..., label=, sources=)` keyword-optional so the older test's 4-arg call still works.
