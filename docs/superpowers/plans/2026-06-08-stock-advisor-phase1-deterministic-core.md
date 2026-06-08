# Stock Advisor — Phase 1: Deterministic Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a free, local, AI-free tool that scans a watchlist of stocks each run and produces a ranked list of momentum/breakout buy candidates with a transparent 0-100 score.

**Architecture:** Deterministic pipeline. Config (YAML) → fetch + validate + cache market data → compute technical indicators → weighted 0-100 score with hard filters → ranked markdown report (console + dated file). No AI and no network calls in the test suite (tests run on synthetic DataFrames). This is the foundation that Phase 2 (AI agents + email) and Phase 3 (sell side + backtest) build on.

**Tech Stack:** Python 3.11+, pandas, yfinance (network fetch only), PyYAML, pytest. Caching via CSV (no extra dependency).

**Project root:** `C:\VS Code\Stock Advisor` (already a git repo with the design spec committed).

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Python dependencies |
| `.gitignore` | Keep secrets, data, reports, caches out of git |
| `README.md` | What it is + how to run (Phase 1 scope) |
| `conftest.py` | Empty file at root so `from src import ...` resolves in tests |
| `src/__init__.py` | Marks `src` as a package |
| `config/watchlist.yaml` | Tickers + settings (shortlist size, lookback, filters) |
| `config/weights.yaml` | Scoring weights (breakout-tilted) |
| `src/config.py` | Load + validate the YAML config files |
| `src/indicators.py` | Pure technical math: SMA, RSI, breakout strength, volume ratio |
| `src/scoring.py` | Turn indicators into a 0-100 score; apply hard filters |
| `src/report.py` | Render ranked + excluded results to markdown text |
| `src/main.py` | Conductor: wire config → data → scoring → report |
| `src/data.py` | Fetch (network), validate, and CSV-cache price history |
| `tests/test_config.py` | Tests for config loading |
| `tests/test_indicators.py` | Tests for indicator math |
| `tests/test_scoring.py` | Tests for scoring + hard filters |
| `tests/test_report.py` | Tests for report rendering |
| `tests/test_data.py` | Tests for data validation + cache round-trip |
| `tests/helpers.py` | Shared synthetic-DataFrame builder for tests |

> **Note on design:** the spec listed indicator math inside `scoring.py`. We split the pure math into `indicators.py` so each file has one clear job and the math is independently testable. This is a small, intentional refinement of the spec.

---

## Task 0: Project scaffold

**Files:**
- Create: `requirements.txt`, `.gitignore`, `README.md`, `conftest.py`, `src/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
pandas>=2.0
yfinance>=0.2.40
PyYAML>=6.0
pytest>=8.0
```

- [ ] **Step 2: Create `.gitignore`**

```
# secrets & generated data — never commit
.env
data/
reports/
logs/
# python
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
```

- [ ] **Step 3: Create `src/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `conftest.py`** at the project root (empty file — its presence makes pytest add the project root to `sys.path` so `from src import ...` works)

```python
```

- [ ] **Step 5: Create `README.md`**

```markdown
# Stock Advisor

Local, free tool that scans a watchlist and emails/prints a ranked list of
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
```

- [ ] **Step 6: Create the data/report/log folders with .gitkeep placeholders so the structure exists**

Run:
```powershell
New-Item -ItemType Directory -Force -Path data,reports,logs,config,tests | Out-Null
```

- [ ] **Step 7: Commit**

```powershell
git add requirements.txt .gitignore README.md conftest.py src/__init__.py
git commit -m "chore: scaffold Stock Advisor Phase 1 project"
```

---

## Task 1: Config loading (`src/config.py`)

**Files:**
- Create: `config/watchlist.yaml`, `config/weights.yaml`, `src/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Create `config/weights.yaml`** (breakout-tilted, from the spec)

```yaml
weights:
  breakout: 30
  volume: 30
  momentum: 20
  trend: 15
  pullback: 5
```

- [ ] **Step 2: Create `config/watchlist.yaml`** (starter list — tickers get finalized with the user later)

```yaml
tickers:
  - AAPL
  - NVDA
  - AMD
  - MSFT
  - TSLA
  - AMZN
  - META
  - GOOGL
  - NFLX
  - AVGO
settings:
  shortlist_size: 8
  lookback_days: 200
  min_price: 5.0
  min_avg_volume: 500000
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
from pathlib import Path
import pytest
from src import config


def _write(tmp_path: Path, watchlist: str, weights: str) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "watchlist.yaml").write_text(watchlist, encoding="utf-8")
    (cfg / "weights.yaml").write_text(weights, encoding="utf-8")
    return cfg


def test_load_watchlist_parses_tickers_and_settings(tmp_path):
    cfg = _write(
        tmp_path,
        "tickers:\n  - aapl\n  - nvda\nsettings:\n  shortlist_size: 4\n",
        "weights:\n  breakout: 30\n",
    )
    wl = config.load_watchlist(cfg)
    assert wl["tickers"] == ["AAPL", "NVDA"]   # upper-cased
    assert wl["settings"]["shortlist_size"] == 4


def test_load_watchlist_rejects_empty(tmp_path):
    cfg = _write(tmp_path, "tickers: []\n", "weights:\n  breakout: 30\n")
    with pytest.raises(ValueError):
        config.load_watchlist(cfg)


def test_load_weights_returns_floats(tmp_path):
    cfg = _write(
        tmp_path,
        "tickers:\n  - aapl\n",
        "weights:\n  breakout: 30\n  volume: 30\n",
    )
    w = config.load_weights(cfg)
    assert w == {"breakout": 30.0, "volume": 30.0}
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.config'`)

- [ ] **Step 3b: Write `src/config.py`**

```python
from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str, config_dir) -> dict:
    path = Path(config_dir) / name
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"{name} is empty")
    return data


def load_watchlist(config_dir=CONFIG_DIR) -> dict:
    data = _load("watchlist.yaml", config_dir)
    tickers = data.get("tickers")
    if not tickers or not isinstance(tickers, list):
        raise ValueError("watchlist.yaml must contain a non-empty 'tickers' list")
    return {
        "tickers": [str(t).upper() for t in tickers],
        "settings": data.get("settings", {}),
    }


def load_weights(config_dir=CONFIG_DIR) -> dict:
    data = _load("weights.yaml", config_dir)
    weights = data.get("weights")
    if not weights:
        raise ValueError("weights.yaml must contain a 'weights' mapping")
    return {k: float(v) for k, v in weights.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add config/watchlist.yaml config/weights.yaml src/config.py tests/test_config.py
git commit -m "feat: load and validate watchlist + weights config"
```

---

## Task 2: Shared test helper (`tests/helpers.py`)

**Files:**
- Create: `tests/helpers.py`

- [ ] **Step 1: Create the synthetic-DataFrame builder** (used by several test files; no network)

```python
import pandas as pd


def make_df(prices, volume=1_000_000):
    """Build an OHLCV DataFrame from a list of close prices.

    Open/High/Low/Close are all set to the price (fine for indicator tests),
    volume is constant unless overridden.
    """
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices,
            "Low": prices,
            "Close": prices,
            "Volume": [volume] * len(prices),
        },
        index=idx,
    )
```

- [ ] **Step 2: Commit**

```powershell
git add tests/helpers.py
git commit -m "test: add synthetic OHLCV DataFrame helper"
```

---

## Task 3: Indicators (`src/indicators.py`)

**Files:**
- Create: `src/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** — `tests/test_indicators.py`

```python
import pandas as pd
from src import indicators
from tests.helpers import make_df


def test_sma_last_value():
    s = pd.Series([1, 2, 3, 4, 5])
    assert indicators.sma(s, 3).iloc[-1] == 4.0   # (3+4+5)/3


def test_rsi_all_gains_is_100():
    # strictly increasing close -> no losses -> RSI = 100
    close = pd.Series(range(1, 40))
    assert round(indicators.rsi(close, 14).iloc[-1], 2) == 100.0


def test_breakout_strength_at_high_is_one():
    close = pd.Series([10, 11, 12])   # latest == rolling max
    assert indicators.breakout_strength(close, 3) == 1.0


def test_volume_ratio_double_average():
    # last 3 volumes: 100, 100, 400 -> avg 200, latest 400 -> ratio 2.0
    vol = pd.Series([100, 100, 100, 400])
    assert round(indicators.volume_ratio(vol, 3), 2) == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indicators.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.indicators'`)

- [ ] **Step 3: Write `src/indicators.py`**

```python
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100). Uses simple rolling averages."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def breakout_strength(close: pd.Series, window: int = 20) -> float:
    """Latest close as a fraction of its rolling-max high (1.0 = at/above high)."""
    recent_high = close.rolling(window).max().iloc[-1]
    latest = close.iloc[-1]
    if pd.isna(recent_high) or recent_high == 0:
        return 0.0
    return float(latest / recent_high)


def volume_ratio(volume: pd.Series, window: int = 20) -> float:
    """Latest volume divided by its rolling average (2.0 = twice normal)."""
    avg = volume.rolling(window).mean().iloc[-1]
    latest = volume.iloc[-1]
    if pd.isna(avg) or avg == 0:
        return 0.0
    return float(latest / avg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_indicators.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/indicators.py tests/test_indicators.py
git commit -m "feat: technical indicators (SMA, RSI, breakout, volume)"
```

---

## Task 4: Scoring engine (`src/scoring.py`)

**Files:**
- Create: `src/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing test** — `tests/test_scoring.py`

```python
from src import scoring
from tests.helpers import make_df

WEIGHTS = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
SETTINGS = {"min_price": 5.0, "min_avg_volume": 500_000}


def test_uptrend_scores_high_and_is_not_excluded():
    # 80 strictly-increasing closes from 50 -> strong trend/breakout/momentum
    df = make_df(list(range(50, 130)))
    result = scoring.score_ticker(df, "TEST", WEIGHTS, SETTINGS)
    assert result["excluded"] is False
    assert 70 <= result["score"] <= 90
    assert set(result["components"]) == {
        "trend", "momentum", "breakout", "volume", "pullback"
    }


def test_penny_stock_is_excluded_by_price_floor():
    df = make_df([2.0] * 60)            # below $5 floor
    result = scoring.score_ticker(df, "PENNY", WEIGHTS, SETTINGS)
    assert result["excluded"] is True
    assert "price" in result["reason"].lower()


def test_illiquid_stock_is_excluded_by_volume_floor():
    df = make_df(list(range(50, 110)), volume=1_000)   # tiny volume
    result = scoring.score_ticker(df, "THIN", WEIGHTS, SETTINGS)
    assert result["excluded"] is True
    assert "volume" in result["reason"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.scoring'`)

- [ ] **Step 3: Write `src/scoring.py`**

```python
import pandas as pd
from src import indicators


def _rsi_subscore(r: float) -> float:
    """RSI -> 0..1. Ideal band 50-70; overbought (>80) scores 0."""
    if pd.isna(r):
        return 0.0
    if r > 80:
        return 0.0
    if 50 <= r <= 70:
        return 1.0
    if r < 50:
        return max(0.0, (r - 30) / 20)   # 30->0, 50->1
    return max(0.0, 1 - (r - 70) / 10)   # 70->1, 80->0


def _breakout_subscore(ratio: float) -> float:
    """Within 10% of the rolling high scales 0..1."""
    return max(0.0, min(1.0, (ratio - 0.9) / 0.1))


def _volume_subscore(ratio: float) -> float:
    """2x average volume or more scores full marks."""
    return max(0.0, min(1.0, ratio / 2.0))


def compute_components(df: pd.DataFrame) -> dict:
    close = df["Close"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    sma20 = float(indicators.sma(close, 20).iloc[-1])
    sma50 = float(indicators.sma(close, 50).iloc[-1])
    rsi_val = float(indicators.rsi(close, 14).iloc[-1])

    trend = (0.5 if price > sma50 else 0.0) + (0.5 if sma20 > sma50 else 0.0)
    momentum = _rsi_subscore(rsi_val)
    breakout = _breakout_subscore(indicators.breakout_strength(close, 20))
    volume_s = _volume_subscore(indicators.volume_ratio(volume, 20))
    pullback = 1.0 if (price > sma50 and price < sma20) else 0.0

    return {
        "trend": trend,
        "momentum": momentum,
        "breakout": breakout,
        "volume": volume_s,
        "pullback": pullback,
    }


def score_ticker(df: pd.DataFrame, ticker: str, weights: dict, settings: dict) -> dict:
    min_price = settings.get("min_price", 5.0)
    min_avg_volume = settings.get("min_avg_volume", 500_000)

    price = float(df["Close"].iloc[-1])
    avg_vol = float(df["Volume"].rolling(20).mean().iloc[-1])

    if price < min_price:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": f"price ${price:.2f} below floor ${min_price:.2f}",
        }
    if pd.isna(avg_vol) or avg_vol < min_avg_volume:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": f"avg volume {avg_vol:,.0f} below floor {min_avg_volume:,}",
        }

    components = compute_components(df)
    total_w = sum(weights.values())
    raw = sum(components[k] * weights.get(k, 0) for k in components)
    score = (100 * raw / total_w) if total_w else 0.0

    return {
        "ticker": ticker,
        "excluded": False,
        "score": score,
        "components": components,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/scoring.py tests/test_scoring.py
git commit -m "feat: weighted 0-100 scoring engine with hard filters"
```

---

## Task 5: Report rendering (`src/report.py`)

**Files:**
- Create: `src/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test** — `tests/test_report.py`

```python
from src import report


def test_report_ranks_candidates_and_lists_excluded():
    scored = [
        {"ticker": "LOW", "excluded": False, "score": 60.0,
         "components": {"trend": 1, "momentum": 1, "breakout": 0.5,
                        "volume": 0.5, "pullback": 0}},
        {"ticker": "HIGH", "excluded": False, "score": 85.0,
         "components": {"trend": 1, "momentum": 1, "breakout": 1,
                        "volume": 1, "pullback": 0}},
        {"ticker": "BAD", "excluded": True, "reason": "price $2.00 below floor $5.00"},
    ]
    text = report.render_report(scored, "2026-06-08")

    assert "2026-06-08" in text
    # HIGH (85) must appear before LOW (60) in the ranked section
    assert text.index("HIGH") < text.index("LOW")
    # excluded ticker shows with its reason
    assert "BAD" in text
    assert "below floor" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.report'`)

- [ ] **Step 3: Write `src/report.py`**

```python
def render_report(scored: list[dict], date_str: str) -> str:
    """Render scored tickers into a ranked markdown report (Phase 1 — no AI)."""
    lines = [f"# Stock Advisor — {date_str}", ""]

    ranked = sorted(
        (s for s in scored if not s["excluded"]),
        key=lambda s: s["score"],
        reverse=True,
    )

    lines.append("## Candidates (ranked)")
    if not ranked:
        lines.append("_No candidates passed the filters today._")
    for s in ranked:
        c = s["components"]
        lines.append(
            f"- **{s['ticker']}**: {s['score']:.0f}/100  "
            f"[trend {c['trend']:.2f} · breakout {c['breakout']:.2f} · "
            f"volume {c['volume']:.2f} · rsi {c['momentum']:.2f}]"
        )

    excluded = [s for s in scored if s["excluded"]]
    if excluded:
        lines.append("")
        lines.append("## Excluded (hard filters)")
        for s in excluded:
            lines.append(f"- {s['ticker']}: {s['reason']}")

    lines.append("")
    lines.append("_Information only — not financial advice._")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/report.py tests/test_report.py
git commit -m "feat: ranked markdown report rendering"
```

---

## Task 6: Data layer (`src/data.py`)

**Files:**
- Create: `src/data.py`
- Test: `tests/test_data.py`

- [ ] **Step 1: Write the failing test** — `tests/test_data.py` (validation + cache round-trip only; no network)

```python
from src import data
from tests.helpers import make_df


def test_validate_accepts_good_data():
    df = make_df(list(range(50, 120)))   # 70 rows, valid prices
    ok, reason = data.validate(df, "GOOD")
    assert ok is True
    assert reason == ""


def test_validate_rejects_too_few_rows():
    df = make_df([10, 11, 12])           # only 3 rows
    ok, reason = data.validate(df, "SHORT")
    assert ok is False
    assert "rows" in reason.lower()


def test_validate_rejects_nonpositive_close():
    df = make_df([10, 0, 12] + list(range(13, 70)))   # contains a 0 close
    ok, reason = data.validate(df, "ZERO")
    assert ok is False


def test_cache_round_trip(tmp_path):
    df = make_df(list(range(50, 120)))
    data.save_cache(df, "RT", tmp_path)
    loaded = data.load_cache("RT", tmp_path)
    assert loaded is not None
    assert list(loaded["Close"]) == list(df["Close"])


def test_load_cache_missing_returns_none(tmp_path):
    assert data.load_cache("NOPE", tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.data'`)

- [ ] **Step 3: Write `src/data.py`**

```python
from pathlib import Path
import pandas as pd

REQUIRED_COLS = ["Open", "High", "Low", "Close", "Volume"]


def validate(df, ticker: str, min_rows: int = 50):
    """Return (ok, reason). reason is '' when ok."""
    if df is None or len(df) == 0:
        return False, f"{ticker}: no data"
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return False, f"{ticker}: missing columns {missing}"
    if len(df) < min_rows:
        return False, f"{ticker}: only {len(df)} rows (need >= {min_rows})"
    if df["Close"].isna().all() or (df["Close"] <= 0).any():
        return False, f"{ticker}: invalid close prices"
    return True, ""


def cache_path(ticker: str, data_dir) -> Path:
    return Path(data_dir) / f"{ticker}.csv"


def save_cache(df, ticker: str, data_dir) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(ticker, data_dir))


def load_cache(ticker: str, data_dir):
    path = cache_path(ticker, data_dir)
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return None


def fetch_history(ticker: str, days: int):
    """Download daily OHLCV from yfinance. Network call — not used in tests."""
    import yfinance as yf

    period_days = int(days * 1.6) + 10  # buffer for weekends/holidays
    df = yf.download(
        ticker,
        period=f"{period_days}d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    # Newer yfinance returns MultiIndex columns even for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/data.py tests/test_data.py
git commit -m "feat: market-data fetch, validation, and CSV caching"
```

---

## Task 7: Conductor (`src/main.py`)

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Write `src/main.py`** (the daily pipeline; this is integration glue — verified by a real run in Task 8)

```python
import datetime as dt
from pathlib import Path

from src import config, data, scoring, report

ROOT = Path(__file__).resolve().parent.parent


def run() -> str:
    wl = config.load_watchlist()
    weights = config.load_weights()
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)

    data_dir = ROOT / "data"
    reports_dir = ROOT / "reports"

    scored = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, lookback)
        ok, reason = data.validate(df, ticker)
        if ok:
            data.save_cache(df, ticker, data_dir)
        else:
            # fall back to last good cache; flag clearly if unusable
            df = data.load_cache(ticker, data_dir)
            cache_ok, _ = data.validate(df, ticker) if df is not None else (False, "")
            if not cache_ok:
                scored.append({
                    "ticker": ticker,
                    "excluded": True,
                    "reason": f"{reason} (no valid cache)",
                })
                continue
        scored.append(scoring.score_ticker(df, ticker, weights, settings))

    date_str = dt.date.today().isoformat()
    text = report.render_report(scored, date_str)

    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
    print(text)
    return text


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Commit**

```powershell
git add src/main.py
git commit -m "feat: daily pipeline conductor (main.py)"
```

---

## Task 8: Full-suite check + first real run

**Files:** none (verification task)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: PASS (all tests across config/indicators/scoring/report/data green)

- [ ] **Step 2: Do a real run against live data** (network — confirms yfinance + the pipeline end-to-end)

Run: `python -m src.main`
Expected: prints a "Stock Advisor — <today>" report with a ranked candidate list, and writes `reports/<today>.md`. Some tickers may show under "Excluded" — that's fine.

- [ ] **Step 3: Sanity-check the output**

Confirm: the ranked list is sorted high→low, scores are 0-100, and `reports/<today>.md` exists. If yfinance returns nothing for every ticker (e.g. no internet), the report will say "No candidates" and tickers will show as excluded with a cache note — that is correct graceful-failure behavior, not a bug.

- [ ] **Step 4: Commit any final tweaks** (only if Step 2/3 surfaced a real issue you fixed)

```powershell
git add -A
git commit -m "fix: Phase 1 end-to-end run adjustments"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Phase 1 scope):**
- Watchlist + settings in editable YAML → Task 1 ✓
- Free data fetch + caching + validation/quality guardrails → Task 6 ✓
- Deterministic breakout-tilted 0-100 scoring → Tasks 3, 4 ✓ (weights match spec: breakout 30 / volume 30 / momentum 20 / trend 15 / pullback 5)
- Hard filters (liquidity floor, price floor, data-valid) → Task 4 ✓
- Ranked report with reasoning + excluded section + disclaimer → Task 5 ✓
- Graceful failure (stale-cache fallback, never silent) → Task 7 ✓
- Conductor wiring the pipeline in order → Task 7 ✓
- Out of Phase 1 scope (deferred to later plans): AI agents, adjudicator, email, positions/exits, backtesting, Task Scheduler automation, `$5` API cap setup. These are Phase 2 & 3.

**Type consistency:** `score_ticker` returns `{ticker, excluded, score, components}` (or `{ticker, excluded, reason}`); `components` keys = `trend, momentum, breakout, volume, pullback`, matching the weight keys and the keys `report.render_report` reads. `data.validate` returns `(ok, reason)` everywhere it's called. Consistent. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; every run step has an exact command + expected result. ✓

---

## What's next (not part of this plan)
After Phase 1 runs cleanly, the next plan is **Phase 2 — AI crew + email** (News/Risk/Context agents on Claude Haiku, adjudicator, Gmail briefing, plus the `$5/month` Anthropic Console cap setup). Then **Phase 3 — sell side + backtesting**.
