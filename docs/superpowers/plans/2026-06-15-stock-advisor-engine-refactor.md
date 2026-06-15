# Stock Advisor Engine Refactor — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the daily-briefing engine from the owner's machine by making "whose run is this?" an explicit `Profile` input, so the same engine can later serve a packaged per-user install whose data lives in `%APPDATA%\StockAdvisor` — without changing any scoring/briefing logic or breaking the owner's personal CLI.

**Architecture:** Introduce a `Profile` (config/data/reports dirs + a secret source) and thread it through `main.run()`, which today derives everything from a module-level `ROOT`. Replace the repo-`.env` load with a precedence-ordered `EnvSecrets` source. Have `run()` return a structured `RunResult` (the object the future web server will render) in addition to writing the report. No engine math changes.

**Tech Stack:** Python 3, pytest (`tmp_path`, `monkeypatch`), existing `src/` package layout, dataclasses. No new runtime dependencies.

**Part of:** `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md` (Section 4). Plans 2 (local web app) and 3 (packaging) build on this.

**Where this runs:** the Stock Advisor repo at `C:\VS Code\Stock Advisor` (not the Website Fuckery workspace). Run all commands from that folder with the venv active: `& .\.venv\Scripts\Activate.ps1`.

---

## File Structure

- **Create `src/profile.py`** — `EnvSecrets` (secret lookup) + `Profile` dataclass with `for_repo()` / `for_base()` factories and `ensure_dirs()`. One responsibility: per-run identity and where its files live.
- **Create `src/results.py`** — `RunResult` dataclass: the structured output of a run.
- **Modify `src/main.py`** — `run()` accepts a `Profile`, reads all paths/secrets from it, returns `RunResult`; `__main__` unchanged in behavior. Adds a `fetch` injection seam for offline testing.
- **Create `tests/test_profile.py`** — unit tests for `EnvSecrets` + `Profile`.
- **Create `tests/test_results.py`** — unit test for `RunResult` construction/defaults.
- **Modify `tests/test_main.py`** — add an offline end-to-end test proving `run(profile=...)` honors the profile's dirs and returns a `RunResult`.
- **Modify `README.md`** — one short note that the engine is profile-aware (owner CLI unchanged).

Design notes locked in by reading the code:
- `config.load_*` already accept a `config_dir` argument — we just pass `profile.config_dir`.
- `broker.resolve_positions(load_positions=, load_overrides=)` already injectable — we pass closures bound to `profile.config_dir`, so **broker.py needs no change**.
- `briefing.render_briefing(...)` / `render_briefing_html(...)` take `(ranked, vetoed, others, excluded, date_str, regime, regime_note, holdings=, rotation_plan=, discovery=)`.
- Downstream modules (`broker`, `llm`, `congress`) read `os.environ` directly; `EnvSecrets.apply_to_environ()` reproduces today's `load_dotenv()` behavior so they keep working unchanged.

---

## Task 1: `EnvSecrets` — precedence-ordered secret source

**Files:**
- Create: `src/profile.py`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile.py`:

```python
from pathlib import Path
from src.profile import EnvSecrets


def test_envsecrets_reads_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text(
        '# comment\nANTHROPIC_API_KEY=sk-abc\nEMAIL_USER="me@x.com"\n\n',
        encoding="utf-8",
    )
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("ANTHROPIC_API_KEY") == "sk-abc"
    assert s.get("EMAIL_USER") == "me@x.com"          # surrounding quotes stripped
    assert s.get("MISSING") is None
    assert s.get("MISSING", "fallback") == "fallback"


def test_envsecrets_missing_file_is_empty(tmp_path):
    s = EnvSecrets(dotenv_path=tmp_path / "nope.env")
    assert s.get("ANYTHING") is None


def test_envsecrets_file_value_beats_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FOO", "from-env")
    (tmp_path / ".env").write_text("FOO=from-file\n", encoding="utf-8")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("FOO") == "from-file"


def test_envsecrets_falls_back_to_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BAR", "from-env")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")   # no file
    assert s.get("BAR") == "from-env"


def test_envsecrets_explicit_values_dict(tmp_path):
    s = EnvSecrets(values={"K": "v"})
    assert s.get("K") == "v"


def test_apply_to_environ_does_not_clobber_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEP", "already")
    s = EnvSecrets(values={"KEEP": "new", "ADD": "added"})
    s.apply_to_environ()
    import os
    assert os.environ["KEEP"] == "already"   # setdefault semantics, matches load_dotenv
    assert os.environ["ADD"] == "added"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.profile'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/profile.py` with only the `EnvSecrets` class for now:

```python
"""Per-run identity: which config/data/reports dirs and secret source to use.

The engine was originally hard-wired to repo-relative paths and a repo-level .env
(one machine, one owner). `Profile` makes "whose run is this?" an explicit input so
the same engine can serve a packaged per-user install whose data lives in, e.g.,
%APPDATA%\\StockAdvisor — without the owner's files ever shipping inside the app.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class EnvSecrets:
    """Secret lookup with a fixed precedence: profile .env file, then process env.

    Values are read once at construction from the .env file (if present) into an
    in-memory dict. `.get()` checks that dict first, then os.environ, so an explicit
    profile secret wins over an ambient one. `.apply_to_environ()` pushes the file
    values into os.environ (without clobbering existing vars) for the downstream
    modules (broker, llm, congress) that still read os.environ directly —
    reproducing today's load_dotenv() behavior.
    """

    def __init__(self, dotenv_path: Optional[Path] = None, values: Optional[dict] = None):
        self._dotenv_path = Path(dotenv_path) if dotenv_path else None
        if values is not None:
            self._values = dict(values)
        else:
            self._values = self._read_dotenv(self._dotenv_path)

    @staticmethod
    def _read_dotenv(path: Optional[Path]) -> dict:
        if not path or not path.exists():
            return {}
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
        return out

    def get(self, key: str, default=None):
        val = self._values.get(key)
        if val is not None and val != "":
            return val
        return os.environ.get(key, default)

    def apply_to_environ(self) -> None:
        for key, val in self._values.items():
            if val != "":
                os.environ.setdefault(key, val)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_profile.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat: EnvSecrets precedence-ordered secret source"
```

---

## Task 2: `Profile` dataclass + factories

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile.py`:

```python
from src.profile import Profile, ROOT


def test_profile_for_repo_uses_repo_dirs():
    p = Profile.for_repo()
    assert p.config_dir == ROOT / "config"
    assert p.data_dir == ROOT / "data"
    assert p.reports_dir == ROOT / "reports"
    assert p.secrets.get("definitely-not-a-real-key") is None


def test_profile_for_base_roots_all_dirs(tmp_path):
    p = Profile.for_base(tmp_path)
    assert p.config_dir == tmp_path / "config"
    assert p.data_dir == tmp_path / "data"
    assert p.reports_dir == tmp_path / "reports"


def test_profile_ensure_dirs_creates_them(tmp_path):
    p = Profile.for_base(tmp_path / "app")
    assert not p.config_dir.exists()
    p.ensure_dirs()
    assert p.config_dir.is_dir()
    assert p.data_dir.is_dir()
    assert p.reports_dir.is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_profile.py -v`
Expected: FAIL with `ImportError: cannot import name 'Profile'`.

- [ ] **Step 3: Write the minimal implementation**

Add to the top of `src/profile.py` (after the existing imports) the `ROOT` constant and a `dataclass` import, then add the `Profile` class below `EnvSecrets`:

```python
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
```

```python
@dataclass(frozen=True)
class Profile:
    config_dir: Path
    data_dir: Path
    reports_dir: Path
    secrets: EnvSecrets

    @classmethod
    def for_repo(cls) -> "Profile":
        """Owner's personal profile: repo-relative dirs + repo .env (back-compat)."""
        return cls(
            config_dir=ROOT / "config",
            data_dir=ROOT / "data",
            reports_dir=ROOT / "reports",
            secrets=EnvSecrets(dotenv_path=ROOT / ".env"),
        )

    @classmethod
    def for_base(cls, base) -> "Profile":
        """Per-user profile rooted at an arbitrary base dir (e.g. %APPDATA%/StockAdvisor)."""
        base = Path(base)
        return cls(
            config_dir=base / "config",
            data_dir=base / "data",
            reports_dir=base / "reports",
            secrets=EnvSecrets(dotenv_path=base / ".env"),
        )

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.data_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_profile.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat: Profile dataclass with repo/base factories"
```

---

## Task 3: `RunResult` structured output

**Files:**
- Create: `src/results.py`
- Test: `tests/test_results.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_results.py`:

```python
from pathlib import Path
from src.results import RunResult


def test_runresult_minimal_defaults():
    r = RunResult(date="2026-06-15", text="hello")
    assert r.date == "2026-06-15"
    assert r.text == "hello"
    assert r.html == ""
    assert r.ranked == [] and r.vetoed == [] and r.holdings == []
    assert r.rotation_plan == {} and r.discovery == {}
    assert r.report_path is None
    assert r.skipped is False


def test_runresult_holds_structured_fields():
    r = RunResult(
        date="2026-06-15", text="t", html="<p>t</p>",
        regime="neutral", regime_note="calm",
        ranked=[{"ticker": "AAA"}], report_path=Path("reports/2026-06-15.md"),
    )
    assert r.html == "<p>t</p>"
    assert r.ranked[0]["ticker"] == "AAA"
    assert r.report_path == Path("reports/2026-06-15.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.results'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/results.py`:

```python
"""Structured result of a daily run, so callers (CLI, future web server) can render
the briefing without re-running the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RunResult:
    date: str
    text: str
    html: str = ""
    regime: str = ""
    regime_note: str = ""
    ranked: list = field(default_factory=list)
    vetoed: list = field(default_factory=list)
    others: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    holdings: list = field(default_factory=list)
    rotation_plan: dict = field(default_factory=dict)
    discovery: dict = field(default_factory=dict)
    report_path: Optional[Path] = None
    skipped: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_results.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/results.py tests/test_results.py
git commit -m "feat: RunResult structured run output"
```

---

## Task 4: Thread `Profile` through `main.run()` and return `RunResult`

This is the core change. `run()` currently reads a module-level `ROOT`, loads config from the default dir, reads secrets from a repo `.env`, and returns a string. After this task it takes a `Profile`, reads everything from it, returns a `RunResult`, and still prints + saves the report exactly as before. The owner's `python -m src.main` keeps working because `run()` defaults to `Profile.for_repo()`.

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
import tests.helpers as helpers
from src.profile import Profile, EnvSecrets


def _seed_min_config(cfg):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "watchlist.yaml").write_text(
        "tickers:\n  - AAA\nsettings:\n  lookback_days: 120\n  shortlist_size: 2\n",
        encoding="utf-8")
    (cfg / "weights.yaml").write_text(
        "weights:\n  breakout: 30\n  volume: 30\n  momentum: 20\n  trend: 15\n  pullback: 5\n",
        encoding="utf-8")
    (cfg / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  news_neg: 10\n  risk_high: 20\n  social: 8\n",
        encoding="utf-8")
    (cfg / "exits.yaml").write_text(
        "defaults:\n  stop_loss_pct: 8\n  take_profit_pct: 20\n"
        "  trend_break_fast: 20\n  trend_break_slow: 50\n"
        "  momentum_fade:\n    rsi_was_above: 70\n    volume_dry_ratio: 0.7\n"
        "backtest:\n  buy_threshold: 65\n  max_hold_days: 60\n"
        "  window_years: 2\n  baseline: equal_weight_watchlist\n",
        encoding="utf-8")
    (cfg / "positions.yaml").write_text("positions: []\n", encoding="utf-8")


def test_run_honors_profile_dirs_and_returns_result(tmp_path, monkeypatch):
    from src import main
    _seed_min_config(tmp_path / "config")

    # Offline: no secrets -> has_llm False -> no Anthropic calls. Stub the network
    # feeds (all of which return empties on failure in production anyway).
    monkeypatch.setattr(main.social, "get_wsb_sentiment", lambda: {})
    monkeypatch.setattr(main.congress, "get_congress_trades", lambda: [])
    monkeypatch.setattr(main.congress, "aggregate_by_ticker", lambda trades: {})
    monkeypatch.setattr(main.market, "get_market_breadth",
                        lambda: {"regime": "neutral", "regime_hint": "VIX calm"})
    monkeypatch.setattr(main.insights, "get_insider_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_analyst_signal", lambda t: None)
    monkeypatch.setattr(main.insights, "get_earnings", lambda t: None)
    monkeypatch.setattr(main.news, "get_headlines", lambda t: [])

    prices = [10 + i * 0.1 for i in range(160)]   # clean rising series
    fake_fetch = lambda ticker, lookback: helpers.make_df(prices)

    profile = Profile(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        secrets=EnvSecrets(values={}),            # no secrets at all
    )

    result = main.run(profile=profile, force=True, fetch=fake_fetch)

    assert result.skipped is False
    assert result.date  # iso date string
    report = tmp_path / "reports" / f"{result.date}.md"
    assert report.exists()                         # written into the PROFILE dir
    assert result.report_path == report
    assert result.html != ""                       # structured html captured
    assert isinstance(result.ranked, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py::test_run_honors_profile_dirs_and_returns_result -v`
Expected: FAIL — `run()` currently takes no `profile`/`fetch` kwargs and returns a `str` (TypeError or AttributeError on `result.skipped`).

- [ ] **Step 3: Rewrite `run()` in `src/main.py`**

Replace the **entire `run()` function** (currently `def run(force: bool = False) -> str:` through its `return text`) with the version below. Also update the imports at the top and the `__main__` block as noted.

First, update the import block at the top of `src/main.py`:

```python
import datetime as dt
import os
from pathlib import Path

import pandas as pd

from src import (config, data, scoring, news, agents, adjudicator, briefing,
                 exits, broker, social, congress, insights, market, rotation)
from src.profile import Profile
from src.results import RunResult

ROOT = Path(__file__).resolve().parent.parent

MAX_ADDS = 3   # most names the daily rotation will recommend buying into
```

Then replace `run()` with:

```python
def run(profile: Profile | None = None, force: bool = False, *, fetch=None) -> RunResult:
    # Make console output crash-proof: the briefing contains emojis that the legacy
    # Windows console (cp1252) cannot encode. UTF-8 + replace avoids a crash without
    # affecting the UTF-8 file that's saved.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if profile is None:
        profile = Profile.for_repo()
    profile.ensure_dirs()
    secrets = profile.secrets
    secrets.apply_to_environ()          # legacy modules (broker/llm/congress) read os.environ
    if fetch is None:
        fetch = data.fetch_history

    date_str = dt.date.today().isoformat()

    # Market closed on weekends/holidays -> no actionable briefing. `--force` overrides.
    if _should_skip_today(dt.date.today(), force):
        msg = "Market closed today (weekend/holiday); skipping briefing (use --force to override)."
        print(msg)
        return RunResult(date=date_str, text=msg, skipped=True)

    wl = config.load_watchlist(profile.config_dir)
    weights = config.load_weights(profile.config_dir)
    caps = config.load_adjudicator(profile.config_dir)
    signals_cfg = config.load_signals(profile.config_dir)
    thr = signals_cfg["thresholds"]
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)
    shortlist_size = settings.get("shortlist_size", 8)

    data_dir = profile.data_dir
    reports_dir = profile.reports_dir

    scored = []
    for ticker in wl["tickers"]:
        df = fetch(ticker, lookback)
        ok, reason = data.validate(df, ticker)
        if ok:
            data.save_cache(df, ticker, data_dir)
        else:
            df = data.load_cache(ticker, data_dir)
            cache_ok, _ = data.validate(df, ticker) if df is not None else (False, "")
            if not cache_ok:
                scored.append({"ticker": ticker, "excluded": True,
                               "reason": f"{reason} (no valid cache)"})
                continue
        result = scoring.score_ticker(df, ticker, weights, settings)
        result["_df"] = df if not result["excluded"] else None
        scored.append(result)

    # ---- evaluate exit signals on current holdings ----
    positions = broker.resolve_positions(
        load_positions=lambda: config.load_positions(profile.config_dir),
        load_overrides=lambda: config.load_position_overrides(profile.config_dir),
        on_error=lambda e: print(f"[holdings: SnapTrade sync failed, using positions.yaml: {e}]"),
    )
    exit_rules = config.load_exit_rules(profile.config_dir)
    df_by_ticker = {s["ticker"]: s.get("_df") for s in scored if s.get("_df") is not None}

    holdings = []
    for pos in positions:
        df = df_by_ticker.get(pos["ticker"])
        ok = df is not None
        if df is None:
            df = fetch(pos["ticker"], lookback)
            ok, _ = data.validate(df, pos["ticker"])
            if ok:
                data.save_cache(df, pos["ticker"], data_dir)
            else:
                df = data.load_cache(pos["ticker"], data_dir)
                ok = df is not None and data.validate(df, pos["ticker"])[0]
        if not ok:
            holdings.append({
                "ticker": pos["ticker"], "current_price": float("nan"),
                "pct_from_entry": 0.0, "signals": [],
                "risk_flag": "no valid price data",
            })
            continue
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

    # ---- market-wide feeds (each falls back gracefully) ----
    wsb_map = social.get_wsb_sentiment()
    congress_trades = congress.get_congress_trades()
    congress_agg = congress.aggregate_by_ticker(congress_trades)
    breadth = market.get_market_breadth()

    for h in holdings:
        h["congress"] = congress_agg.get(h["ticker"])
        h["insider"] = insights.get_insider_signal(h["ticker"])

    known = set(wl["tickers"]) | {h["ticker"] for h in holdings}
    discovery = _discovery_feed(congress_trades, wsb_map, known, signals_cfg)

    has_llm = bool(secrets.get("ANTHROPIC_API_KEY"))
    client = None
    if has_llm:
        from src import llm
        client = llm.AnthropicClient()

    if has_llm:
        summary = _build_market_summary(scored) + " " + breadth["regime_hint"]
        context = agents.context_agent(client, summary)
    else:
        context = {"regime": breadth["regime"], "note": breadth["regime_hint"]}

    cands = sorted((s for s in scored if not s["excluded"]),
                   key=lambda s: s["score"], reverse=True)
    shortlist = cands[:shortlist_size]
    others = [{"ticker": s["ticker"], "score": s["score"]} for s in cands[shortlist_size:]]
    excluded = [{"ticker": s["ticker"], "reason": s["reason"]}
                for s in scored if s["excluded"]]

    ranked, vetoed = [], []
    for s in shortlist:
        ticker = s["ticker"]
        wsb_sig = wsb_map.get(ticker)
        congress_sig = congress_agg.get(ticker)
        analyst_sig = insights.get_analyst_signal(ticker)
        insider_sig = insights.get_insider_signal(ticker)
        earnings_sig = insights.get_earnings(ticker)

        if has_llm:
            headlines = news.get_headlines(ticker)
            recent_closes = list(s["_df"]["Close"].tail(10))
            nv = agents.news_agent(client, ticker, headlines)
            rv = agents.risk_agent(client, ticker, recent_closes, headlines)
            if wsb_sig and (wsb_sig.get("mentions") or 0) >= thr["social_min_mentions"]:
                chatter = [f"{wsb_sig['mentions']} WSB mentions, "
                           f"{wsb_sig.get('mentions_change')} change in 24h, rank {wsb_sig.get('rank')}"]
                sv = agents.social_agent(client, ticker, chatter)
            else:
                sv = dict(agents.NEUTRAL_SOCIAL)
        else:
            nv, rv = dict(agents.NEUTRAL_NEWS), dict(agents.NEUTRAL_RISK)
            sv = dict(agents.NEUTRAL_SOCIAL)

        adjd = adjudicator.adjudicate(
            {"ticker": ticker, "score": s["score"]}, nv, rv, context, caps,
            congress=congress_sig, wsb=wsb_sig, social_view=sv,
            analyst=analyst_sig, insider=insider_sig, earnings=earnings_sig, thresholds=thr,
        )
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    ranked.sort(key=lambda r: r["final_score"], reverse=True)

    if has_llm:
        for h in holdings:
            try:
                df_h = df_by_ticker.get(h["ticker"])
                recent = list(df_h["Close"].tail(10)) if df_h is not None else []
                rv = agents.risk_agent(client, h["ticker"], recent, news.get_headlines(h["ticker"]))
                if rv.get("veto") or rv.get("risk_level") == "high":
                    h["risk_flag"] = rv.get("reason") or "elevated risk"
            except Exception:
                pass

    rotation_plan = rotation.build_rotation_plan(
        holdings, ranked, conviction=exit_rules["backtest"]["buy_threshold"], max_adds=MAX_ADDS,
    )

    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
    )
    html = briefing.render_briefing_html(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
    )
    report_path = reports_dir / f"{date_str}.md"
    report_path.write_text(text, encoding="utf-8")
    print(text)
    if not has_llm:
        print("\n[AI agents disabled: no ANTHROPIC_API_KEY — running on deterministic signals only]")

    # Optional email (only when all EMAIL_* secrets are present)
    if all(secrets.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            briefing.send_email(
                f"Stock Advisor — {date_str}", text,
                host=secrets.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(secrets.get("EMAIL_PORT", "465")),
                user=secrets.get("EMAIL_USER"),
                password=secrets.get("EMAIL_PASSWORD"),
                to_addr=secrets.get("EMAIL_TO"),
                html_body=html,
            )
            print("[briefing emailed]")
        except Exception as e:
            print(f"[email failed: {e}]")

    return RunResult(
        date=date_str, text=text, html=html,
        regime=context["regime"], regime_note=context["note"],
        ranked=ranked, vetoed=vetoed, others=others, excluded=excluded,
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
        report_path=report_path, skipped=False,
    )
```

Finally, confirm the `__main__` block at the bottom of `src/main.py` reads:

```python
if __name__ == "__main__":
    import sys
    run(force="--force" in sys.argv[1:])
```

(No change needed — `run()` now returns a `RunResult` but the CLI ignores the return value and the report is printed inside `run()` exactly as before.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_main.py::test_run_honors_profile_dirs_and_returns_result -v`
Expected: PASS. If `data.validate` rejects the synthetic series (e.g. needs more rows), widen the `range(160)` series or adjust `lookback_days` in `_seed_min_config` — the assertion targets (profile dir used, `RunResult` returned) stay the same.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "refactor: thread Profile through run(), return RunResult"
```

---

## Task 5: Confirm the owner CLI is unbroken + document it

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS — all pre-existing tests plus the new `test_profile.py`, `test_results.py`, and the `run()` test. No test should require network (the new one is fully offline).

- [ ] **Step 2: Smoke-test the owner CLI path (optional, requires network)**

Run: `& .\.venv\Scripts\python.exe -m src.main --force`
Expected: prints a briefing and writes `reports/<today>.md` exactly as before — proving `Profile.for_repo()` is wired correctly. (Skip if offline; the automated test already covers the wiring.)

- [ ] **Step 3: Add a short README note**

In `README.md`, directly under the `# Stock Advisor` intro paragraph, add:

```markdown
> **Profile-aware engine:** `main.run()` accepts a `Profile` (config/data/reports
> dirs + secret source). With no argument it uses `Profile.for_repo()` — the owner's
> repo files and `.env` — so `python -m src.main` is unchanged. A packaged per-user
> build passes `Profile.for_base(<%APPDATA%/StockAdvisor>)` instead, keeping each
> person's data isolated from the program files. See
> `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: note the profile-aware engine"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Section 4 of the design):**
- "Introduce a `Profile` object carrying config_dir, data_dir, reports_dir, secrets" → Tasks 1–2. ✓
- "Change secret lookup order to credential store → profile .env → environment" → Task 1 implements **profile .env → environment**; the OS credential store layer is explicitly a later plan (design Section 11 open item) and slots in front of `EnvSecrets` without changing callers. ✓ (scoped)
- "`run()` returns a structured result" → Task 3 (`RunResult`) + Task 4. ✓
- "Owner's personal CLI keeps working" → `run()` defaults to `Profile.for_repo()`; `__main__` unchanged; Task 5 verifies. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the one tuning note in Task 4 Step 4 is a contingency, not a missing implementation. ✓

**Type/name consistency:** `EnvSecrets`, `Profile.for_repo`/`for_base`/`ensure_dirs`, `RunResult(date, text, html, regime, regime_note, ranked, vetoed, others, excluded, holdings, rotation_plan, discovery, report_path, skipped)`, and `run(profile, force, *, fetch)` are used identically across tasks and tests. Renderer and `broker.resolve_positions` signatures match the current source. ✓

**Out of scope (later plans):** FastAPI server + browser UI (Plan 2), onboarding/first-run profile seeding in `%APPDATA%`, OS credential store, PyInstaller + Inno Setup packaging, build-hygiene exclusions (Plan 3).
