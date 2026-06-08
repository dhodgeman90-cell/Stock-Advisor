# Stock Advisor Phase 3 — Sell Side + Backtesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic sell-side exit engine (driven by a manual `positions.yaml`) that leads the daily briefing, plus a trade-by-trade backtester that replays the scoring engine over history and compares it to buy-and-hold.

**Architecture:** Mirror the existing "B+" split — exits are 100% deterministic and unit-testable (`exits.py`); the backtest replays those same deterministic rules over historical data with no AI calls; the AI Risk agent only *annotates* held names in the briefing, never drives exits. New tunable numbers live in `config/exits.yaml`; holdings live in `config/positions.yaml`.

**Tech Stack:** Python 3.14, pandas, PyYAML, pytest. Runs in the `.venv` at the repo root. All commands use `& .\.venv\Scripts\python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-08-stock-advisor-phase3-exits-backtest-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `config/exits.yaml` | **new** — exit thresholds (`defaults`) + backtest params (`backtest`) |
| `config/positions.yaml` | **new** — manual holdings template |
| `src/config.py` | add `load_exit_rules()` and `load_positions()` |
| `src/exits.py` | **new** — pure `evaluate_exit(df, position, rules)` deterministic engine |
| `src/briefing.py` | add `render_holdings_section()`; holdings lead `render_briefing()` |
| `src/backtest.py` | **new** — `simulate_ticker`, `summarize`, `buy_and_hold`, `render_backtest_report`, `run` |
| `src/main.py` | load positions/rules, fetch union set, evaluate exits, optional Risk annotation, prepend holdings |
| `tests/test_config.py` | extend with exit-rules + positions loader tests |
| `tests/test_exits.py` | **new** |
| `tests/test_briefing.py` | extend with holdings-section tests |
| `tests/test_backtest.py` | **new** |
| `README.md` | document positions, exit signals, backtest command |

**Conventions to follow (from the existing codebase):**
- Tests build OHLCV frames with `tests/helpers.py::make_df(prices, volume=...)`.
- Config-loader tests write YAML into a `tmp_path/config` dir and pass that dir in.
- Loaders raise `ValueError` on malformed input.
- `main.py` is the untested conductor — verified by a real run, not unit tests (no `test_main.py` exists; keep it that way).
- Run tests: `& .\.venv\Scripts\python.exe -m pytest -q`

---

## Task 0: Create the Phase 3 branch

The user works one git branch per phase. The spec and this plan are already committed to `master`.

- [ ] **Step 1: Create and switch to the branch**

This makes a new branch off `master` so Phase 3 work is isolated; nothing is published until we merge.

Run:
```powershell
git checkout -b phase-3-exits-backtest
```
Expected: `Switched to a new branch 'phase-3-exits-backtest'`

- [ ] **Step 2: Confirm a clean starting point**

Run:
```powershell
git status
& .\.venv\Scripts\python.exe -m pytest -q
```
Expected: working tree clean; all existing tests pass (≈35 passed).

---

## Task 1: Config — exit rules + positions loaders

**Files:**
- Create: `config/exits.yaml`
- Create: `config/positions.yaml`
- Modify: `src/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the config files**

Create `config/exits.yaml`:
```yaml
defaults:
  stop_loss_pct: 8         # sell if price <= entry * (1 - 0.08)
  take_profit_pct: 20      # trim/sell if price >= entry * (1 + 0.20)
  trend_break_fast: 20     # watch/trim if close < 20-day MA
  trend_break_slow: 50     # sell if close < 50-day MA
  momentum_fade:
    rsi_was_above: 70      # had been overbought...
    volume_dry_ratio: 0.7  # ...and volume now < 0.7x its 20-day average
backtest:
  buy_threshold: 65        # simulate a buy when base score >= this
  max_hold_days: 60        # force-close a trade after N trading days
  window_years: 2          # how much history to replay
  baseline: equal_weight_watchlist
```

Create `config/positions.yaml` (empty template — the user fills this in as they trade):
```yaml
# Your current holdings. Update this file whenever you buy or sell.
# Each entry needs at least `ticker` and `entry_price`.
# Optional per-position overrides: stop_loss_pct, take_profit_pct.
positions: []
#  - ticker: NVDA
#    entry_price: 120.50
#    entry_date: 2026-06-01
#    shares: 2
#    stop_loss_pct: 10
#    take_profit_pct: 25
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_config.py`:
```python
def test_load_exit_rules_returns_defaults_and_backtest(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "exits.yaml").write_text(
        "defaults:\n"
        "  stop_loss_pct: 8\n"
        "  take_profit_pct: 20\n"
        "  trend_break_fast: 20\n"
        "  trend_break_slow: 50\n"
        "  momentum_fade:\n"
        "    rsi_was_above: 70\n"
        "    volume_dry_ratio: 0.7\n"
        "backtest:\n"
        "  buy_threshold: 65\n"
        "  max_hold_days: 60\n"
        "  window_years: 2\n"
        "  baseline: equal_weight_watchlist\n",
        encoding="utf-8",
    )
    rules = config.load_exit_rules(cfg)
    assert rules["defaults"]["stop_loss_pct"] == 8
    assert rules["backtest"]["buy_threshold"] == 65


def test_load_exit_rules_rejects_missing_sections(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "exits.yaml").write_text("defaults:\n  stop_loss_pct: 8\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_exit_rules(cfg)


def test_load_positions_parses_and_uppercases(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text(
        "positions:\n"
        "  - ticker: nvda\n"
        "    entry_price: 120.5\n"
        "    entry_date: 2026-06-01\n"
        "    shares: 2\n",
        encoding="utf-8",
    )
    positions = config.load_positions(cfg)
    assert len(positions) == 1
    assert positions[0]["ticker"] == "NVDA"
    assert positions[0]["entry_price"] == 120.5
    assert positions[0]["stop_loss_pct"] is None   # no override


def test_load_positions_empty_when_missing_or_blank(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    # no file at all
    assert config.load_positions(cfg) == []
    # present but empty list
    (cfg / "positions.yaml").write_text("positions: []\n", encoding="utf-8")
    assert config.load_positions(cfg) == []


def test_load_positions_rejects_missing_required_fields(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text(
        "positions:\n  - ticker: NVDA\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        config.load_positions(cfg)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'load_exit_rules'`

- [ ] **Step 4: Implement the loaders**

Append to `src/config.py`:
```python
def load_exit_rules(config_dir=CONFIG_DIR) -> dict:
    data = _load("exits.yaml", config_dir)
    defaults = data.get("defaults")
    backtest = data.get("backtest")
    if not defaults or not backtest:
        raise ValueError("exits.yaml must contain 'defaults' and 'backtest' mappings")
    return {"defaults": defaults, "backtest": backtest}


def load_positions(config_dir=CONFIG_DIR) -> list:
    path = Path(config_dir) / "positions.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    raw = data.get("positions") or []
    if not isinstance(raw, list):
        raise ValueError("positions.yaml 'positions' must be a list")
    out = []
    for p in raw:
        if "ticker" not in p or "entry_price" not in p:
            raise ValueError("each position requires 'ticker' and 'entry_price'")
        out.append({
            "ticker": str(p["ticker"]).upper(),
            "entry_price": float(p["entry_price"]),
            "entry_date": str(p.get("entry_date", "")),
            "shares": p.get("shares"),
            "stop_loss_pct": p.get("stop_loss_pct"),
            "take_profit_pct": p.get("take_profit_pct"),
        })
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: PASS (all config tests green)

- [ ] **Step 6: Commit**

```powershell
git add config/exits.yaml config/positions.yaml src/config.py tests/test_config.py
git commit -m "feat: exit-rules and positions config loaders"
```

---

## Task 2: Deterministic exit engine (`exits.py`)

**Files:**
- Create: `src/exits.py`
- Test: `tests/test_exits.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exits.py`:
```python
import pandas as pd
from src import exits
from tests.helpers import make_df

RULES = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {},
}


def _types(result):
    return [s["type"] for s in result["signals"]]


def test_stop_loss_fires_alone_on_steady_uptrend_below_entry():
    # Steady uptrend so price is ABOVE both MAs (no trend break); RSI still
    # climbing (no fade); we just bought too high so we're 8%+ underwater.
    df = make_df(list(range(50, 110)))           # last close = 109
    position = {"ticker": "T", "entry_price": 119.0}   # 109 is ~8.4% below 119
    result = exits.evaluate_exit(df, position, RULES)
    assert _types(result) == ["stop_loss"]
    assert result["pct_from_entry"] < 0


def test_take_profit_fires_when_up_target():
    df = make_df(list(range(50, 110)))           # last close = 109
    position = {"ticker": "T", "entry_price": 90.0}    # 109 is ~21% above 90
    result = exits.evaluate_exit(df, position, RULES)
    assert "take_profit" in _types(result)


def test_trend_break_lists_slow_before_fast():
    # Rise then fall below both moving averages, but only ~3% below entry
    # (so stop-loss does NOT fire).
    prices = list(range(50, 101)) + [95, 90, 85, 80, 78, 76, 74, 72, 70, 68]
    df = make_df(prices)                          # last close = 68
    position = {"ticker": "T", "entry_price": 70.0}    # 68 is ~2.9% below entry
    result = exits.evaluate_exit(df, position, RULES)
    types = _types(result)
    assert "trend_break_slow" in types
    assert "trend_break_fast" in types
    assert types.index("trend_break_slow") < types.index("trend_break_fast")
    assert "stop_loss" not in types


def test_momentum_fade_fires_on_rolling_rsi_and_dry_volume():
    prices = list(range(50, 106)) + [104, 103, 102, 101]   # peak then roll over
    vols = [1_000_000] * (len(prices) - 1) + [150_000]      # volume dries up
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    df = pd.DataFrame(
        {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": vols},
        index=idx,
    )
    position = {"ticker": "T", "entry_price": 100.0}        # ~1% up: no stop/target
    result = exits.evaluate_exit(df, position, RULES)
    assert "momentum_fade" in _types(result)


def test_per_position_override_suppresses_default_stop():
    df = make_df(list(range(50, 110)))            # last close = 109
    position = {"ticker": "T", "entry_price": 121.0, "stop_loss_pct": 15}
    # 109 is ~9.9% below 121 -> default 8% would fire, but override 15% does not
    result = exits.evaluate_exit(df, position, RULES)
    assert "stop_loss" not in _types(result)


def test_clean_holding_returns_no_signals():
    df = make_df(list(range(50, 110)))            # uptrend, price above MAs
    position = {"ticker": "T", "entry_price": 108.0}   # ~0.9% up
    result = exits.evaluate_exit(df, position, RULES)
    assert result["signals"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_exits.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.exits'`

- [ ] **Step 3: Implement the engine**

Create `src/exits.py`:
```python
import pandas as pd
from src import indicators


def _resolve(position, defaults, key):
    """Per-position override beats the default; None means 'use default'."""
    val = position.get(key)
    return defaults[key] if val is None else val


def evaluate_exit(df, position, rules) -> dict:
    """Deterministic exit signals for one holding. Pure function, no I/O.

    Signals are returned in fixed priority order:
    stop_loss -> take_profit -> trend_break_slow -> trend_break_fast -> momentum_fade.
    """
    defaults = rules["defaults"]
    close = df["Close"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    entry = float(position["entry_price"])
    pct_from_entry = ((price - entry) / entry * 100) if entry else 0.0

    stop_pct = float(_resolve(position, defaults, "stop_loss_pct"))
    target_pct = float(_resolve(position, defaults, "take_profit_pct"))
    fast = int(defaults["trend_break_fast"])
    slow = int(defaults["trend_break_slow"])
    fade = defaults["momentum_fade"]

    sma_fast = float(indicators.sma(close, fast).iloc[-1])
    sma_slow = float(indicators.sma(close, slow).iloc[-1])
    rsi_series = indicators.rsi(close, 14)
    today_rsi = float(rsi_series.iloc[-1])
    recent_rsi_max = float(rsi_series.tail(5).max())
    vol_ratio = indicators.volume_ratio(volume, 20)

    signals = []

    if price <= entry * (1 - stop_pct / 100):
        signals.append({
            "type": "stop_loss", "level": "sell", "emoji": "🔴",
            "detail": f"down {pct_from_entry:.1f}% from entry (stop -{stop_pct:.0f}%)",
        })

    if price >= entry * (1 + target_pct / 100):
        signals.append({
            "type": "take_profit", "level": "trim", "emoji": "🟢",
            "detail": f"up {pct_from_entry:.1f}% from entry (target +{target_pct:.0f}%)",
        })

    if not pd.isna(sma_slow) and price < sma_slow:
        signals.append({
            "type": "trend_break_slow", "level": "sell", "emoji": "🔴",
            "detail": f"close ${price:.2f} below {slow}-day MA ${sma_slow:.2f}",
        })

    if not pd.isna(sma_fast) and price < sma_fast:
        signals.append({
            "type": "trend_break_fast", "level": "watch", "emoji": "🟡",
            "detail": f"close ${price:.2f} below {fast}-day MA ${sma_fast:.2f}",
        })

    if (not pd.isna(recent_rsi_max)
            and recent_rsi_max > float(fade["rsi_was_above"])
            and today_rsi < recent_rsi_max
            and vol_ratio < float(fade["volume_dry_ratio"])):
        signals.append({
            "type": "momentum_fade", "level": "watch", "emoji": "🟡",
            "detail": (f"RSI rolling over (peaked {recent_rsi_max:.0f}) "
                       f"on drying volume ({vol_ratio:.1f}x avg)"),
        })

    return {
        "ticker": position["ticker"],
        "current_price": price,
        "pct_from_entry": pct_from_entry,
        "signals": signals,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_exits.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```powershell
git add src/exits.py tests/test_exits.py
git commit -m "feat: deterministic exit-signal engine"
```

---

## Task 3: Holdings section in the briefing

**Files:**
- Modify: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing.py`:
```python
def _holding(ticker, price, pct, signals, risk_flag=None):
    h = {"ticker": ticker, "current_price": price, "pct_from_entry": pct, "signals": signals}
    if risk_flag:
        h["risk_flag"] = risk_flag
    return h


def test_render_holdings_section_empty():
    text = briefing.render_holdings_section([])
    assert "No tracked positions" in text


def test_render_holdings_section_shows_signals_and_clean_lines():
    holdings = [
        _holding("NVDA", 109.0, -9.2,
                 [{"type": "stop_loss", "level": "sell", "emoji": "🔴",
                   "detail": "down 9.2% from entry (stop -8%)"}]),
        _holding("AAPL", 150.0, 5.0, []),   # clean
    ]
    text = briefing.render_holdings_section(holdings)
    assert "NVDA" in text
    assert "stop loss" in text                 # underscores rendered as spaces
    assert "down 9.2%" in text
    assert "no exit signal" in text            # clean holding line for AAPL


def test_render_briefing_puts_holdings_above_candidates():
    ranked = [_adjudicated("HI", 88, 80, "new deal", "low", "no flags", ["+15 catalyst"])]
    holdings = [_holding("NVDA", 109.0, -9.2,
                         [{"type": "stop_loss", "level": "sell", "emoji": "🔴",
                           "detail": "down 9.2%"}])]
    text = briefing.render_briefing(ranked, [], [], [], "2026-06-08",
                                    "risk_on", "Upbeat.", holdings=holdings)
    assert text.index("NVDA") < text.index("Top candidates")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q`
Expected: FAIL — `AttributeError: module 'src.briefing' has no attribute 'render_holdings_section'`

- [ ] **Step 3: Implement the holdings renderer and wire it in**

In `src/briefing.py`, add this function above `render_briefing`:
```python
def render_holdings_section(holdings) -> str:
    """Markdown block for current holdings + their exit signals. Leads the briefing."""
    lines = ["## 📊 Your holdings"]
    if not holdings:
        lines.append("_No tracked positions. Keep `positions.yaml` current as you buy and sell._")
        return "\n".join(lines)
    for h in holdings:
        lines.append(
            f"- **{h['ticker']}**: ${h['current_price']:.2f} "
            f"({h['pct_from_entry']:+.1f}% from entry)"
        )
        if h["signals"]:
            for s in h["signals"]:
                lines.append(f"    - {s['emoji']} {s['type'].replace('_', ' ')}: {s['detail']}")
        else:
            lines.append("    - 🟢 holding — no exit signal")
        if h.get("risk_flag"):
            lines.append(f"    - ⚠️ {h['risk_flag']}")
    lines.append("")
    lines.append("_Reminder: keep `positions.yaml` current as you buy and sell._")
    return "\n".join(lines)
```

Then change the `render_briefing` signature and insert the holdings section at the top. Replace:
```python
def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note) -> str:
    """Render the enriched daily briefing (Phase 2). `ranked` is pre-sorted by final_score."""
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
        "",
        "## Top candidates",
    ]
```
with:
```python
def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note,
                    holdings=None) -> str:
    """Render the enriched daily briefing (Phase 2 + Phase 3 holdings).

    `ranked` is pre-sorted by final_score. `holdings` (Phase 3) leads the briefing.
    """
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
        "",
        render_holdings_section(holdings),
        "",
        "## Top candidates",
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -q`
Expected: PASS (existing briefing tests still green + 3 new)

- [ ] **Step 5: Commit**

```powershell
git add src/briefing.py tests/test_briefing.py
git commit -m "feat: holdings/exit section leads the daily briefing"
```

---

## Task 4: Backtester (`backtest.py`)

**Files:**
- Create: `src/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest.py`:
```python
import pandas as pd
from src import backtest
from tests.helpers import make_df

# Low buy_threshold (0) so any valid day triggers entry, letting us test the
# entry-timing and exit logic deterministically without hand-tuning a score.
RULES_ENTER_ALWAYS = {
    "defaults": {
        "stop_loss_pct": 8,
        "take_profit_pct": 20,
        "trend_break_fast": 20,
        "trend_break_slow": 50,
        "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7},
    },
    "backtest": {"buy_threshold": 0, "max_hold_days": 60},
}
SETTINGS = {"min_price": 5.0, "min_avg_volume": 500_000}
WEIGHTS = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}


def test_simulate_ticker_closes_on_stop_loss_and_enters_next_day_open():
    # 62 flat days (so day 60 scores and triggers entry), then a drop to 92.
    prices = [100.0] * 62 + [92.0]               # index 62 close = 92 -> -8% stop
    df = make_df(prices)
    # Distinguish the entry day's open from its close to prove next-day-open entry.
    df.loc[df.index[61], "Open"] = 101.0
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, RULES_ENTER_ALWAYS)
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == 101.0             # entered at day-61 OPEN, not close
    assert t["reason"] == "stop_loss"
    assert round(t["return_pct"], 1) == round((92.0 - 101.0) / 101.0 * 100, 1)


def test_simulate_ticker_no_trade_when_threshold_unreachable():
    prices = [100.0] * 70
    df = make_df(prices)
    rules = {**RULES_ENTER_ALWAYS,
             "backtest": {"buy_threshold": 99, "max_hold_days": 60}}
    trades = backtest.simulate_ticker(df, "T", WEIGHTS, SETTINGS, rules)
    assert trades == []


def test_summarize_computes_win_rate_and_averages():
    trades = [
        {"return_pct": 20.0, "hold_days": 10, "reason": "take_profit"},
        {"return_pct": -8.0, "hold_days": 3, "reason": "stop_loss"},
        {"return_pct": 12.0, "hold_days": 5, "reason": "take_profit"},
    ]
    s = backtest.summarize(trades)
    assert s["count"] == 3
    assert round(s["win_rate"], 1) == 66.7
    assert round(s["avg_gain"], 1) == 16.0
    assert round(s["avg_loss"], 1) == -8.0
    assert s["by_reason"]["take_profit"] == 2


def test_summarize_handles_no_trades():
    s = backtest.summarize([])
    assert s["count"] == 0


def test_buy_and_hold_equal_weight_average():
    histories = {
        "A": make_df([100.0, 110.0]),    # +10%
        "B": make_df([100.0, 130.0]),    # +30%
    }
    assert round(backtest.buy_and_hold(histories), 1) == 20.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.backtest'`

- [ ] **Step 3: Implement the backtester**

Create `src/backtest.py`:
```python
import datetime as dt
from collections import Counter
from pathlib import Path

from src import config, data, scoring, exits

ROOT = Path(__file__).resolve().parent.parent
MIN_HISTORY = 60   # need >=50 rows for the 50-day MA before the first decision


def simulate_ticker(df, ticker, weights, settings, rules) -> list:
    """Trade-by-trade replay for one ticker. Returns a list of closed trades.

    Entry: when base score >= buy_threshold and no trade is open, buy at the
    NEXT day's open (no look-ahead). Exit: on a 'sell'-level signal or a
    take_profit, evaluated against that day's close; force-close at max_hold_days.
    One open trade per ticker at a time.
    """
    bt = rules["backtest"]
    threshold = float(bt["buy_threshold"])
    max_hold = int(bt["max_hold_days"])

    trades = []
    open_trade = None
    n = len(df)
    i = MIN_HISTORY
    while i < n:
        window = df.iloc[: i + 1]
        if open_trade is None:
            res = scoring.score_ticker(window, ticker, weights, settings)
            if (not res.get("excluded")) and res["score"] >= threshold and (i + 1) < n:
                entry_idx = i + 1
                open_trade = {
                    "entry_idx": entry_idx,
                    "entry_price": float(df["Open"].iloc[entry_idx]),
                    "entry_date": df.index[entry_idx],
                }
                i = entry_idx           # resume exit checks the day AFTER entry
        else:
            position = {"ticker": ticker, "entry_price": open_trade["entry_price"]}
            ev = exits.evaluate_exit(window, position, rules)
            held_days = i - open_trade["entry_idx"]
            sell = any(s["level"] == "sell" for s in ev["signals"])
            take = any(s["type"] == "take_profit" for s in ev["signals"])
            force = held_days >= max_hold
            if sell or take or force:
                exit_price = float(df["Close"].iloc[i])
                if ev["signals"] and (sell or take):
                    reason = ev["signals"][0]["type"]
                else:
                    reason = "max_hold"
                ret = (exit_price - open_trade["entry_price"]) / open_trade["entry_price"] * 100
                trades.append({
                    "ticker": ticker,
                    "entry_date": str(open_trade["entry_date"].date()),
                    "entry_price": open_trade["entry_price"],
                    "exit_date": str(df.index[i].date()),
                    "exit_price": exit_price,
                    "return_pct": ret,
                    "hold_days": held_days,
                    "reason": reason,
                })
                open_trade = None
        i += 1
    return trades


def summarize(trades) -> dict:
    if not trades:
        return {"count": 0, "win_rate": 0.0, "avg_gain": 0.0, "avg_loss": 0.0,
                "avg_hold": 0.0, "total_return": 0.0, "by_reason": Counter()}
    rets = [t["return_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    return {
        "count": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_gain": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "avg_hold": sum(t["hold_days"] for t in trades) / len(trades),
        "total_return": sum(rets),
        "by_reason": Counter(t["reason"] for t in trades),
    }


def buy_and_hold(histories) -> float:
    """Equal-weight buy-and-hold return (%) across the watchlist over the window."""
    rets = []
    for df in histories.values():
        first = float(df["Close"].iloc[0])
        last = float(df["Close"].iloc[-1])
        if first:
            rets.append((last - first) / first * 100)
    return (sum(rets) / len(rets)) if rets else 0.0


def render_backtest_report(summary, baseline, trades, date_str) -> str:
    L = [
        f"# Stock Advisor — Backtest ({date_str})",
        "",
        f"- Trades: **{summary['count']}**",
        f"- Win rate: **{summary['win_rate']:.0f}%**",
        f"- Avg gain: **{summary['avg_gain']:+.1f}%**  |  Avg loss: **{summary['avg_loss']:+.1f}%**",
        f"- Avg hold: **{summary['avg_hold']:.0f}** trading days",
        f"- Strategy total return (sum of trade returns): **{summary['total_return']:+.1f}%**",
        f"- Buy-and-hold baseline (equal-weight watchlist): **{baseline:+.1f}%**",
        "",
        "## Exit reasons",
    ]
    if summary["by_reason"]:
        for reason, count in summary["by_reason"].most_common():
            L.append(f"- {reason.replace('_', ' ')}: {count}")
    else:
        L.append("_No trades._")
    L.append("")
    L.append("> Caveat: a good backtest is encouraging, not a guarantee. Overfitting is a "
             "real risk — treat these numbers skeptically and confirm with paper trading.")
    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"


def run() -> str:
    wl = config.load_watchlist()
    weights = config.load_weights()
    rules = config.load_exit_rules()
    settings = wl["settings"]
    years = int(rules["backtest"]["window_years"])
    days = years * 365

    histories = {}
    all_trades = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, days)
        ok, _ = data.validate(df, ticker)
        if not ok:
            continue
        histories[ticker] = df
        all_trades.extend(simulate_ticker(df, ticker, weights, settings, rules))

    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-{date_str}.md").write_text(text, encoding="utf-8")

    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```powershell
git add src/backtest.py tests/test_backtest.py
git commit -m "feat: trade-by-trade backtester with buy-and-hold baseline"
```

---

## Task 5: Wire exits into the daily pipeline (`main.py`)

**Files:**
- Modify: `src/main.py`

`main.py` is the untested conductor, so this task is verified by a real run (Step 3), consistent with the project's existing approach (there is no `test_main.py`).

- [ ] **Step 1: Add positions/exits handling**

In `src/main.py`, update the import line:
```python
from src import config, data, scoring, news, agents, adjudicator, briefing, report
```
to:
```python
from src import config, data, scoring, news, agents, adjudicator, briefing, report, exits
```

After the scoring loop (right after the `for ticker in wl["tickers"]:` loop that builds `scored`), add the holdings computation. Insert before the `# Graceful fallback: no API key` comment:
```python
    # ---- Phase 3: evaluate exit signals on current holdings ----
    positions = config.load_positions()
    exit_rules = config.load_exit_rules()
    df_by_ticker = {s["ticker"]: s.get("_df") for s in scored if s.get("_df") is not None}

    holdings = []
    for pos in positions:
        df = df_by_ticker.get(pos["ticker"])
        if df is None:
            # held ticker not on the watchlist — fetch it (with cache fallback)
            df = data.fetch_history(pos["ticker"], lookback)
            ok, _ = data.validate(df, pos["ticker"])
            if ok:
                data.save_cache(df, pos["ticker"], data_dir)
            else:
                df = data.load_cache(pos["ticker"], data_dir)
        valid = df is not None and data.validate(df, pos["ticker"])[0]
        if not valid:
            holdings.append({
                "ticker": pos["ticker"], "current_price": float("nan"),
                "pct_from_entry": 0.0, "signals": [],
                "risk_flag": "no valid price data",
            })
            continue
        holdings.append(exits.evaluate_exit(df, pos, exit_rules))
```

- [ ] **Step 2: Render holdings in both output paths**

In the no-API-key branch, replace:
```python
        text = report.render_report(clean, date_str)
        (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
```
with:
```python
        text = briefing.render_holdings_section(holdings) + "\n\n" + report.render_report(clean, date_str)
        (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
```

In the AI branch, after the shortlist loop builds `ranked`/`vetoed` and before `text = briefing.render_briefing(...)`, add the optional Risk-agent annotation on holdings:
```python
    # Optional: annotate held names with the Risk agent (does not drive exits)
    for h in holdings:
        try:
            df_h = df_by_ticker.get(h["ticker"])
            recent = list(df_h["Close"].tail(10)) if df_h is not None else []
            rv = agents.risk_agent(client, h["ticker"], recent, news.get_headlines(h["ticker"]))
            if rv.get("veto") or rv.get("risk_level") == "high":
                h["risk_flag"] = rv.get("reason", "elevated risk")
        except Exception:
            pass   # annotation is best-effort; never break the briefing
```

Then update the `render_briefing` call to pass holdings:
```python
    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings,
    )
```

- [ ] **Step 3: Verify with a real run**

First add one real holding to test the section end-to-end. Edit `config/positions.yaml` to (pick any watchlist ticker so data is already fetched):
```yaml
positions:
  - ticker: NVDA
    entry_price: 100.00
    entry_date: 2026-05-01
```

Run (no API key needed — exits are deterministic; explain to the user this does a live data fetch and prints the briefing):
```powershell
& .\.venv\Scripts\python.exe -m src.main
```
Expected: the printed briefing now opens with a `## 📊 Your holdings` section showing NVDA, its current price, % from entry, and either exit signals or "🟢 holding — no exit signal". The rest of the report is unchanged.

Then run the backtest to confirm it works on live data:
```powershell
& .\.venv\Scripts\python.exe -m src.backtest
```
Expected: prints a backtest report with trade count, win rate, and the buy-and-hold comparison; saves `reports/backtest-YYYY-MM-DD.md`.

- [ ] **Step 4: Restore the empty positions template**

Revert the test holding so the committed template stays empty:
```yaml
positions: []
```
(Keep the commented example block.)

- [ ] **Step 5: Run the full test suite**

Run: `& .\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS — all prior tests plus the new exits/backtest/briefing/config tests.

- [ ] **Step 6: Commit**

```powershell
git add src/main.py config/positions.yaml
git commit -m "feat: wire deterministic exits + optional risk annotation into daily run"
```

---

## Task 6: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

Run: `& .\.venv\Scripts\python.exe -c "print(open('README.md', encoding='utf-8').read())"`
(Read it so the new section matches the existing tone and structure.)

- [ ] **Step 2: Document Phase 3**

Add a "Holdings & exit signals" subsection explaining that the user edits `config/positions.yaml` (ticker + entry_price required; optional `stop_loss_pct`/`take_profit_pct` overrides), what each exit signal means (🔴 sell, 🟢 trim/sell, 🟡 watch/trim), and that exit thresholds live in `config/exits.yaml`. Add a "Backtesting" subsection with the run command:
```powershell
& .\.venv\Scripts\python.exe -m src.backtest
```
and a one-line note that results are saved to `reports/backtest-YYYY-MM-DD.md` and should be treated skeptically (overfitting is real).

- [ ] **Step 3: Commit**

```powershell
git add README.md
git commit -m "docs: document positions, exit signals, and backtesting (Phase 3)"
```

---

## Task 7: Finish the branch

- [ ] **Step 1: Final full-suite run**

Run: `& .\.venv\Scripts\python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 2: Hand off to the finishing-a-development-branch skill**

Invoke `superpowers:finishing-a-development-branch` to choose how to integrate `phase-3-exits-backtest` into `master` (the user prefers a clean merge per phase, then deletes the branch — matching Phase 1 and Phase 2).

---

## Self-Review Notes (author check against the spec)

- **Spec §3 (config):** Task 1 — both files + loaders + tests. ✓
- **Spec §4 (exits.py, 5 signals, priority order, overrides):** Task 2 — all five signals, priority ordering test, override test. ✓
- **Spec §5 (briefing leads with holdings):** Task 3 — `render_holdings_section` + top placement test. ✓
- **Spec §6 (main wiring, union fetch, optional Risk annotation, no-key path):** Task 5 — union via per-holding fetch, best-effort Risk annotation, holdings prepended in both paths. ✓
- **Spec §7 (backtest: next-day-open entry, close-based exits, max_hold, equal-weight baseline, report):** Task 4 — `simulate_ticker`/`summarize`/`buy_and_hold`/`render_backtest_report` + tests for entry timing, stop close, no-trade, summary math, baseline math. ✓
- **Spec §8 (tests, no network/AI in tests):** all new tests use synthetic frames / low thresholds; no live calls. ✓
- **Type consistency:** `evaluate_exit` return shape (`ticker`/`current_price`/`pct_from_entry`/`signals[{type,level,emoji,detail}]`) is consumed identically by `render_holdings_section` and `simulate_ticker`. `simulate_ticker(df, ticker, weights, settings, rules)` signature matches its test calls. `render_briefing(..., holdings=None)` matches the updated call site. ✓
- **Out of scope:** Task Scheduler automation is deferred to Phase 4 (not in this plan). ✓
