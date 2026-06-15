# Stock Advisor Local Web App — Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the profile-aware engine (Plan 1) in a thin local FastAPI server + plain HTML/JS browser dashboard so a non-technical user can view today's briefing, edit their watchlist and manual positions, and trigger a run — all on `127.0.0.1`, with each user's data living in their own `%APPDATA%\StockAdvisor` profile.

**Architecture:** Three layers, bottom two shared with the future hosted product (spec Section 3 & 10). The **engine** is unchanged — `main.run(profile, force, *, fetch)` already returns a `RunResult`. The **server** is a thin FastAPI app built by a `create_app(profile)` factory; routes are split into small modules (`routes_core`, `routes_settings`, `routes_positions`, `routes_briefing`) and every route resolves "whose request is this?" through a single `deps.get_profile` dependency — the seam that becomes per-tenant auth in the cloud. The **UI** is three static files served by the server. A launcher (`src/app.py`) resolves the per-user profile, seeds first-run defaults, picks a free port, starts uvicorn, and opens the browser.

**Tech Stack:** Python 3, FastAPI + uvicorn (server), Pydantic v2 (request validation, comes with FastAPI), plain HTML/CSS/vanilla JS (UI), pytest + `fastapi.testclient.TestClient` + `httpx` (tests). No JS framework, no build step.

**Part of:** `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md` (Sections 5 & 6). Builds on Plan 1 (`2026-06-15-stock-advisor-engine-refactor.md`, merged to `main`). Plan 3 (packaging: PyInstaller + Inno Setup, Section 7 build hygiene + Section 8) builds on this.

**Scope (decided with the owner):** MVP core only — Briefing, Watchlist, Positions, Run, launcher, first-run/disclaimer. The **Integrations** page (BYO Anthropic key, BYO Gmail) and `PUT /api/secrets` are **deferred to a short follow-on (Plan 2b)** per spec Section 9, because the desktop secret-storage mechanism (Windows DPAPI/keyring) is throwaway relative to the cloud product, whose value is the owner proxying one key. What carries over — clean API/UI layering and the single `get_profile` seam — is built here regardless. The Integrations nav tab ships as a static "coming soon" panel so the four-screen layout from Section 5 is honored.

**Where this runs:** the Stock Advisor repo at `C:\VS Code\Stock Advisor` (not the Website Fuckery workspace). Do the work on a feature branch (e.g. `local-web-app`), mirroring how Plan 1 was branched then fast-forward merged. Activate the venv once per session, then run all commands from the repo root:

```powershell
& .\.venv\Scripts\Activate.ps1
```

After activation `pytest` and `python` resolve to the venv. (If you prefer not to activate: prefix commands with `& .\.venv\Scripts\python.exe -m`.)

---

## File Structure

New engine/server modules (in `src/`, the existing package):

- **`src/resources.py`** — locate bundled, read-only resource dirs (`defaults/`, `ui/`). One helper (`base_path()`) returns the repo root in dev and the PyInstaller bundle root when frozen, so Plan 3 needs no code change here — only a `--add-data` mapping. One responsibility: *where the shipped files are.*
- **`src/apppaths.py`** — `user_base_dir()` resolves the per-user profile base (`%APPDATA%\StockAdvisor`, override via `STOCK_ADVISOR_HOME`, cross-platform `~/.stockadvisor` fallback). One responsibility: *where this user's data lives.*
- **`src/onboarding.py`** — `seed_profile(profile)` copies missing default configs from `resources.defaults_dir()` into the profile's `config/`; disclaimer state helpers (`disclaimer_accepted` / `accept_disclaimer`) persist a tiny `app_state.json`. One responsibility: *first-run setup.*
- **`src/deps.py`** — `get_profile(request)` returns `request.app.state.profile`. **The DI seam** the routes depend on; becomes per-tenant auth in the cloud. One responsibility: *whose request is this.*
- **`src/server.py`** — `create_app(profile) -> FastAPI`: sets `app.state`, registers the route modules, returns the app. One responsibility: *app assembly.*
- **`src/routes_core.py`** — static UI serving (`/`, `/app.js`, `/style.css`) + `GET /api/state` + `POST /api/disclaimer/accept`.
- **`src/routes_settings.py`** — `GET/PUT /api/settings` (watchlist tickers + settings).
- **`src/routes_positions.py`** — `GET/PUT /api/positions` (manual holdings).
- **`src/routes_briefing.py`** — `POST /api/run` + `GET /api/briefing/today` (+ run wrapper that persists `reports/<date>.html` and caches the last result).
- **`src/app.py`** — the launcher / process entry point (`python -m src.app`).

Modified:
- **`src/config.py`** — add `save_watchlist`, `save_positions`, and an atomic-write helper (only `load_*` exists today).
- **`requirements.txt`** — add `fastapi`, `uvicorn`, `httpx`.
- **`README.md`** — a "Run the local app" section.

New bundled resources (top level, so Plan 3's `--add-data` maps them to the bundle root unchanged):
- **`defaults/`** — `watchlist.yaml` (the owner's vetted tickers, positions stripped), `weights.yaml`, `adjudicator.yaml`, `exits.yaml`, `positions.yaml` (empty). Sane starter configs; **none of the owner's personal data**.
- **`ui/`** — `index.html`, `app.js`, `style.css`.

New tests (in `tests/`):
- `test_config_save.py`, `test_resources.py`, `test_apppaths.py`, `test_onboarding.py`,
  `test_server_core.py`, `test_server_settings.py`, `test_server_positions.py`,
  `test_server_briefing.py`, `test_ui_static.py`, `test_app_launcher.py`.

Design facts locked in by reading the code (do not re-derive):
- `main.run(profile=None, force=False, *, fetch=None) -> RunResult`; with no profile it uses `Profile.for_repo()`. It **prints** the briefing and writes `reports/<date>.md` (markdown), but does **not** persist HTML — the server persists `reports/<date>.html` itself.
- `RunResult` fields: `date, text, html, regime, regime_note, ranked, vetoed, others, excluded, holdings, rotation_plan, discovery, report_path, skipped`.
- `briefing.render_briefing_html(...)` (already called inside `run()`) returns a **self-contained inline-styled `<div>` fragment** — safe to inject into the Briefing pane as-is.
- `Profile.for_base(base)` roots `config/ data/ reports/` under `base`; `Profile.ensure_dirs()` creates them. `profile.secrets` is an `EnvSecrets` (the read-side secret abstraction — no write path needed for the MVP).
- `config.load_watchlist(config_dir) -> {"tickers": [...UPPER...], "settings": {...}}`; `config.load_positions(config_dir) -> [ {ticker, entry_price, entry_date(str), shares, stop_loss_pct, take_profit_pct, trailing_stop_pct}, ... ]`. Loaders accept a `config_dir` positional arg.
- The repo root `conftest.py` already puts `src` and `tests` on `sys.path`; tests import `from src.x import y` and use `tmp_path` / `monkeypatch`.

---

## Task 1: Config save functions (`save_watchlist`, `save_positions`)

The CRUD endpoints need to write YAML; today `config.py` only reads. Add atomic writers that round-trip cleanly through the existing loaders.

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config_save.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_save.py`:

```python
import pytest
from src import config


def test_save_watchlist_roundtrips(tmp_path):
    config.save_watchlist(tmp_path, ["aapl", "MSFT", "aapl"],
                          {"shortlist_size": 3, "lookback_days": 120})
    wl = config.load_watchlist(tmp_path)
    assert wl["tickers"] == ["AAPL", "MSFT"]          # upper-cased + de-duped, order kept
    assert wl["settings"]["shortlist_size"] == 3
    assert wl["settings"]["lookback_days"] == 120


def test_save_watchlist_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        config.save_watchlist(tmp_path, [], {})


def test_save_positions_roundtrips(tmp_path):
    config.save_positions(tmp_path, [
        {"ticker": "aapl", "entry_price": 150, "entry_date": "2026-01-02", "shares": 10},
        {"ticker": "msft", "entry_price": 300},
    ])
    pos = config.load_positions(tmp_path)
    assert pos[0]["ticker"] == "AAPL" and pos[0]["entry_price"] == 150.0
    assert pos[0]["entry_date"] == "2026-01-02" and pos[0]["shares"] == 10
    assert pos[1]["ticker"] == "MSFT" and pos[1]["entry_date"] == ""   # omitted -> "" on load


def test_save_positions_empty_writes_loadable_file(tmp_path):
    config.save_positions(tmp_path, [])
    assert config.load_positions(tmp_path) == []


def test_save_positions_rejects_bad_price(tmp_path):
    with pytest.raises(ValueError):
        config.save_positions(tmp_path, [{"ticker": "X", "entry_price": 0}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config_save.py -v`
Expected: FAIL with `AttributeError: module 'src.config' has no attribute 'save_watchlist'`.

- [ ] **Step 3: Add the writers to `src/config.py`**

Add these imports at the top of `src/config.py` (it currently imports only `from pathlib import Path` and `import yaml`):

```python
import os
import tempfile
```

Append to the end of `src/config.py`:

```python
def _atomic_write_yaml(path, data) -> None:
    """Write YAML to `path` atomically (temp file + os.replace) so a crash mid-write
    never leaves a half-written config the loaders would choke on."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_watchlist(config_dir, tickers, settings=None) -> None:
    """Persist watchlist.yaml. Tickers are upper-cased and de-duplicated (order kept).
    Mirrors what load_watchlist() expects."""
    clean, seen = [], set()
    for t in tickers:
        u = str(t).strip().upper()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    if not clean:
        raise ValueError("watchlist must contain at least one ticker")
    _atomic_write_yaml(Path(config_dir) / "watchlist.yaml",
                       {"tickers": clean, "settings": dict(settings or {})})


def save_positions(config_dir, positions) -> None:
    """Persist positions.yaml in the shape load_positions() reads. Optional fields
    (entry_date, shares, *_pct) are omitted when blank/None to keep the file clean."""
    out = []
    for p in positions:
        ticker = str(p["ticker"]).strip().upper()
        entry_price = float(p["entry_price"])
        if entry_price <= 0:
            raise ValueError(f"{ticker}: entry_price must be greater than 0")
        row = {"ticker": ticker, "entry_price": entry_price}
        if p.get("entry_date"):
            row["entry_date"] = str(p["entry_date"])
        for k in ("shares", "stop_loss_pct", "take_profit_pct", "trailing_stop_pct"):
            if p.get(k) is not None:
                row[k] = p[k]
        out.append(row)
    _atomic_write_yaml(Path(config_dir) / "positions.yaml", {"positions": out})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config_save.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_save.py
git commit -m "feat: atomic save_watchlist/save_positions config writers"
```

---

## Task 2: Resource + per-user-dir resolution

Two tiny, pure modules the launcher and server depend on: where the shipped files live, and where this user's data lives.

**Files:**
- Create: `src/resources.py`, `src/apppaths.py`
- Test: `tests/test_resources.py`, `tests/test_apppaths.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resources.py`:

```python
from src import resources


def test_base_path_is_repo_root_in_dev():
    # In dev (not frozen) base_path() is the repo root that contains the src package.
    assert (resources.base_path() / "src" / "profile.py").exists()


def test_defaults_and_ui_dirs_hang_off_base():
    assert resources.defaults_dir() == resources.base_path() / "defaults"
    assert resources.ui_dir() == resources.base_path() / "ui"
```

Create `tests/test_apppaths.py`:

```python
from pathlib import Path
from src.apppaths import user_base_dir


def test_override_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_ADVISOR_HOME", str(tmp_path / "custom"))
    assert user_base_dir() == tmp_path / "custom"


def test_appdata_used_when_no_override(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCK_ADVISOR_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert user_base_dir() == tmp_path / "Roaming" / "StockAdvisor"


def test_home_fallback_when_no_appdata(monkeypatch):
    monkeypatch.delenv("STOCK_ADVISOR_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert user_base_dir() == Path.home() / ".stockadvisor"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resources.py tests/test_apppaths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.resources'`.

- [ ] **Step 3: Write the implementations**

Create `src/resources.py`:

```python
"""Locate bundled, read-only resources (default configs + the static UI).

In development these live in the repo. Under a PyInstaller build, files added with
--add-data are unpacked to sys._MEIPASS at runtime. base_path() returns the right
root for both, so callers never branch on "are we frozen?" — Plan 3 only has to map
defaults/ and ui/ into the bundle; this module is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path


def base_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent   # repo root (parent of src/)


def defaults_dir() -> Path:
    return base_path() / "defaults"


def ui_dir() -> Path:
    return base_path() / "ui"
```

Create `src/apppaths.py`:

```python
"""Resolve the per-user profile base directory (where THIS user's data lives).

Precedence:
  1. STOCK_ADVISOR_HOME env var  — explicit override (tests, portable installs).
  2. %APPDATA%\\StockAdvisor      — the Windows beta target.
  3. ~/.stockadvisor             — cross-platform fallback (dev on mac/Linux).
The returned dir is NOT created here; the caller seeds it via onboarding.seed_profile.
"""
from __future__ import annotations

import os
from pathlib import Path


def user_base_dir() -> Path:
    override = os.environ.get("STOCK_ADVISOR_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "StockAdvisor"
    return Path.home() / ".stockadvisor"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resources.py tests/test_apppaths.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resources.py src/apppaths.py tests/test_resources.py tests/test_apppaths.py
git commit -m "feat: resource + per-user profile dir resolution"
```

---

## Task 3: Bundled default configs + first-run onboarding

Create the shipped `defaults/` configs (the owner's vetted watchlist, positions stripped) and the onboarding module that seeds a fresh profile from them and tracks disclaimer acceptance. The seeding test doubles as proof the bundled defaults are valid for the real loaders.

**Files:**
- Create: `defaults/watchlist.yaml`, `defaults/weights.yaml`, `defaults/adjudicator.yaml`, `defaults/exits.yaml`, `defaults/positions.yaml`
- Create: `src/onboarding.py`
- Test: `tests/test_onboarding.py`

- [ ] **Step 1: Create the bundled default config files**

Create `defaults/watchlist.yaml` (owner's vetted tickers; settings copied; no positions):

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

Create `defaults/weights.yaml`:

```yaml
weights:
  breakout: 30
  volume: 30
  momentum: 20
  trend: 15
  pullback: 5
```

Create `defaults/adjudicator.yaml`:

```yaml
caps:
  catalyst: 15
  news_negative: 10
  risk_high: 20
  risk_medium: 8
  regime: 5
  congress_buy: 18
  congress_sell: 18
  insider_buy: 12
  insider_sell: 10
  analyst: 8
  earnings_soon: 6
  social: 10
```

Create `defaults/exits.yaml`:

```yaml
defaults:
  stop_loss_pct: 8
  take_profit_pct: 20
  take_profit_mode: trailing
  trailing_stop_pct: 12
  trend_break_fast: 20
  trend_break_slow: 50
  trend_break_slow_level: watch
  momentum_fade:
    rsi_was_above: 70
    volume_dry_ratio: 0.7
backtest:
  buy_threshold: 65
  max_hold_days: 250
  window_years: 2
  cost_pct_per_side: 0.1
  baseline: equal_weight_watchlist
```

Create `defaults/positions.yaml` (a new user holds nothing):

```yaml
positions: []
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_onboarding.py`:

```python
from src import onboarding, config
from src.profile import Profile


def test_seed_copies_defaults_and_they_load(tmp_path):
    p = Profile.for_base(tmp_path)
    copied = onboarding.seed_profile(p)
    assert set(copied) == {
        "watchlist.yaml", "weights.yaml", "adjudicator.yaml",
        "exits.yaml", "positions.yaml",
    }
    # the seeded files are valid input for the real loaders
    assert config.load_watchlist(p.config_dir)["tickers"]
    assert config.load_weights(p.config_dir)
    assert config.load_adjudicator(p.config_dir)
    assert config.load_exit_rules(p.config_dir)
    assert config.load_positions(p.config_dir) == []


def test_seed_is_idempotent_and_nondestructive(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    config.save_watchlist(p.config_dir, ["ZZZZ"], {"shortlist_size": 1})  # user edits
    copied = onboarding.seed_profile(p)                                   # second run
    assert copied == []                                                   # nothing re-copied
    assert config.load_watchlist(p.config_dir)["tickers"] == ["ZZZZ"]     # not clobbered


def test_disclaimer_state_roundtrip(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    assert onboarding.disclaimer_accepted(p) is False
    onboarding.accept_disclaimer(p)
    assert onboarding.disclaimer_accepted(p) is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_onboarding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.onboarding'`.

- [ ] **Step 4: Write `src/onboarding.py`**

```python
"""First-run setup for a fresh per-user profile.

seed_profile() copies the bundled default configs into the profile's config dir,
but only the ones that don't exist yet — so it is safe to call on every launch and
never overwrites a user's edits. Disclaimer acceptance is stored in a small JSON
state file inside the profile so the welcome screen shows exactly once.
"""
from __future__ import annotations

import json
import shutil

from src import resources

DEFAULT_FILES = [
    "watchlist.yaml",
    "weights.yaml",
    "adjudicator.yaml",
    "exits.yaml",
    "positions.yaml",
]


def seed_profile(profile) -> list:
    """Copy any missing default config into profile.config_dir. Returns the names
    actually copied (empty on an already-seeded profile)."""
    profile.ensure_dirs()
    src_dir = resources.defaults_dir()
    copied = []
    for name in DEFAULT_FILES:
        dest = profile.config_dir / name
        if not dest.exists():
            shutil.copyfile(src_dir / name, dest)
            copied.append(name)
    return copied


def _state_path(profile):
    return profile.config_dir / "app_state.json"


def _load_state(profile) -> dict:
    path = _state_path(profile)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def disclaimer_accepted(profile) -> bool:
    return bool(_load_state(profile).get("disclaimer_accepted"))


def accept_disclaimer(profile) -> None:
    profile.ensure_dirs()
    state = _load_state(profile)
    state["disclaimer_accepted"] = True
    _state_path(profile).write_text(json.dumps(state, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_onboarding.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add defaults/ src/onboarding.py tests/test_onboarding.py
git commit -m "feat: bundled default configs + first-run profile seeding"
```

---

## Task 4: Server skeleton — `create_app`, the `get_profile` seam, static UI + state/disclaimer

Stand up the FastAPI app via a `create_app(profile)` factory, the single `get_profile` dependency, static file serving, and the disclaimer endpoints. Create minimal **stub** UI files so the static routes resolve; Task 8 replaces them with the real dashboard.

**Files:**
- Create: `src/deps.py`, `src/server.py`, `src/routes_core.py`
- Create (stubs): `ui/index.html`, `ui/app.js`, `ui/style.css`
- Test: `tests/test_server_core.py`

- [ ] **Step 1: Create the stub UI files**

Create `ui/index.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Stock Advisor</title></head>
<body><p>Stock Advisor — UI stub (replaced in Task 8).</p></body>
</html>
```

Create `ui/app.js`:

```javascript
// stub — replaced in Task 8
```

Create `ui/style.css`:

```css
/* stub — replaced in Task 8 */
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_server_core.py`:

```python
from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_serves_ui_shell(tmp_path):
    client = _client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "Stock Advisor" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.js").headers["content-type"].startswith("application/javascript")
    assert client.get("/style.css").status_code == 200
    assert client.get("/style.css").headers["content-type"].startswith("text/css")


def test_disclaimer_flow(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/state").json()["disclaimer_accepted"] is False
    assert client.post("/api/disclaimer/accept").json()["ok"] is True
    assert client.get("/api/state").json()["disclaimer_accepted"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_server_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.server'` (and/or httpx/fastapi import errors — install deps if so; they are added formally in Task 10, but to run these tests now: `pip install fastapi uvicorn httpx`).

- [ ] **Step 4: Write `src/deps.py`**

```python
"""The single 'whose request is this?' seam.

In the local beta the app is started for exactly one Profile, stored on app.state.
In the future hosted product this function becomes the per-tenant auth lookup
(session/token -> tenant profile). Routes depend on it and never change.
"""
from __future__ import annotations

from fastapi import Request

from src.profile import Profile


def get_profile(request: Request) -> Profile:
    return request.app.state.profile
```

- [ ] **Step 5: Write `src/routes_core.py`**

```python
"""Core routes: serve the static UI and handle disclaimer state."""
from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse, Response

from src import resources, onboarding
from src.deps import get_profile


def register(app) -> None:
    ui = resources.ui_dir()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (ui / "index.html").read_text(encoding="utf-8")

    @app.get("/app.js")
    def app_js():
        return Response((ui / "app.js").read_text(encoding="utf-8"),
                        media_type="application/javascript")

    @app.get("/style.css")
    def style_css():
        return Response((ui / "style.css").read_text(encoding="utf-8"),
                        media_type="text/css")

    @app.get("/api/state")
    def state(profile=Depends(get_profile)):
        return {"disclaimer_accepted": onboarding.disclaimer_accepted(profile)}

    @app.post("/api/disclaimer/accept")
    def accept(profile=Depends(get_profile)):
        onboarding.accept_disclaimer(profile)
        return {"ok": True}
```

- [ ] **Step 6: Write `src/server.py`**

```python
"""Thin local FastAPI app. create_app(profile) is the factory: tests build one over a
tmp profile; the launcher (src/app.py) builds one over the real %APPDATA% profile.
Route groups live in small routes_* modules and are registered here."""
from __future__ import annotations

from fastapi import FastAPI

from src.profile import Profile


def create_app(profile: Profile) -> FastAPI:
    app = FastAPI(title="Stock Advisor (local)")
    app.state.profile = profile
    app.state.last_result = None   # most recent RunResult, set by routes_briefing

    from src import routes_core
    routes_core.register(app)

    return app
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_server_core.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add src/deps.py src/server.py src/routes_core.py ui/ tests/test_server_core.py
git commit -m "feat: FastAPI app factory, get_profile seam, static UI + disclaimer"
```

---

## Task 5: Settings endpoints (`GET/PUT /api/settings`)

The Watchlist screen reads and writes the watchlist doc (tickers + the settings the UI exposes: shortlist size, lookback). Validation via a Pydantic body model; persistence via `save_watchlist` (Task 1).

> Forward-compatibility note: the spec's `/api/settings` is described as covering weights and exit rules too. The MVP UI only edits the watchlist (spec Section 5, screen 2), so this endpoint covers that. Weights/exits can be added as extra keys on the same JSON later without breaking the contract — the bundled defaults are sane in the meantime.

**Files:**
- Create: `src/routes_settings.py`
- Modify: `src/server.py`
- Test: `tests/test_server_settings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_settings.py`:

```python
from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_get_settings_returns_seeded_watchlist(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/settings").json()
    assert "AAPL" in body["tickers"]
    assert body["settings"]["shortlist_size"] == 8


def test_put_settings_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/settings", json={
        "tickers": ["spy", "qqq"],
        "settings": {"shortlist_size": 3, "lookback_days": 120},
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/api/settings").json()
    assert body["tickers"] == ["SPY", "QQQ"]          # upper-cased on save
    assert body["settings"]["shortlist_size"] == 3
    assert body["settings"]["lookback_days"] == 120


def test_put_settings_empty_tickers_is_400(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/settings", json={"tickers": [], "settings": {}})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_settings.py -v`
Expected: FAIL — `GET /api/settings` returns 404 (route not registered yet).

- [ ] **Step 3: Write `src/routes_settings.py`**

```python
"""Watchlist settings: GET current, PUT replacement."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config
from src.deps import get_profile


class WatchSettings(BaseModel):
    shortlist_size: int = 8
    lookback_days: int = 200
    min_price: float = 5.0
    min_avg_volume: int = 500000


class SettingsBody(BaseModel):
    tickers: list[str]
    settings: WatchSettings = WatchSettings()


def register(app) -> None:
    @app.get("/api/settings")
    def get_settings(profile=Depends(get_profile)):
        wl = config.load_watchlist(profile.config_dir)
        return {"tickers": wl["tickers"], "settings": wl["settings"]}

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, profile=Depends(get_profile)):
        try:
            config.save_watchlist(profile.config_dir, body.tickers,
                                  body.settings.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True}
```

- [ ] **Step 4: Register it in `create_app`**

In `src/server.py`, replace:

```python
    return app
```

with:

```python
    from src import routes_settings
    routes_settings.register(app)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_server_settings.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/routes_settings.py src/server.py tests/test_server_settings.py
git commit -m "feat: GET/PUT /api/settings (watchlist)"
```

---

## Task 6: Positions endpoints (`GET/PUT /api/positions`)

The Positions screen reads and writes manual holdings. Optional fields are nullable in the body model; `save_positions` (Task 1) omits the blank ones.

**Files:**
- Create: `src/routes_positions.py`
- Modify: `src/server.py`
- Test: `tests/test_server_positions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_positions.py`:

```python
from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_get_positions_starts_empty(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/positions").json()["positions"] == []


def test_put_positions_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/positions", json={"positions": [
        {"ticker": "aapl", "entry_price": 150.0, "entry_date": "2026-01-02", "shares": 10},
    ]})
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/api/positions").json()
    assert body["positions"][0]["ticker"] == "AAPL"
    assert body["positions"][0]["entry_price"] == 150.0
    assert body["positions"][0]["entry_date"] == "2026-01-02"
    assert body["positions"][0]["shares"] == 10


def test_put_positions_bad_price_is_400(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/positions", json={"positions": [
        {"ticker": "X", "entry_price": 0},
    ]})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_positions.py -v`
Expected: FAIL — `GET /api/positions` returns 404.

- [ ] **Step 3: Write `src/routes_positions.py`**

```python
"""Manual positions: GET current, PUT replacement."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config
from src.deps import get_profile


class PositionBody(BaseModel):
    ticker: str
    entry_price: float
    entry_date: Optional[str] = None
    shares: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None


class PositionsBody(BaseModel):
    positions: list[PositionBody]


def register(app) -> None:
    @app.get("/api/positions")
    def get_positions(profile=Depends(get_profile)):
        return {"positions": config.load_positions(profile.config_dir)}

    @app.put("/api/positions")
    def put_positions(body: PositionsBody, profile=Depends(get_profile)):
        try:
            config.save_positions(profile.config_dir,
                                  [p.model_dump() for p in body.positions])
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True}
```

- [ ] **Step 4: Register it in `create_app`**

In `src/server.py`, replace:

```python
    return app
```

with:

```python
    from src import routes_positions
    routes_positions.register(app)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_server_positions.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/routes_positions.py src/server.py tests/test_server_positions.py
git commit -m "feat: GET/PUT /api/positions (manual holdings)"
```

---

## Task 7: Run + briefing endpoints (`POST /api/run`, `GET /api/briefing/today`)

`POST /api/run` calls the engine (`main.run`, which already exists and returns a `RunResult`), persists the styled HTML to `reports/<date>.html` (the engine only writes the `.md`), and caches the result in `app.state`. `GET /api/briefing/today` returns the in-memory result if present, else the newest saved `.html` (so a briefing survives an app restart), else `{"status": "none"}`. Tests stay offline by monkeypatching `main.run`.

**Files:**
- Create: `src/routes_briefing.py`
- Modify: `src/server.py`
- Test: `tests/test_server_briefing.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_briefing.py`:

```python
from fastapi.testclient import TestClient

from src import server, onboarding, main
from src.profile import Profile
from src.results import RunResult


def _profile(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return profile


def test_run_persists_html_and_caches(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    fake = RunResult(date="2026-06-15", text="t", html="<div>HI</div>", skipped=False,
                     report_path=profile.reports_dir / "2026-06-15.md")
    monkeypatch.setattr(main, "run", lambda profile, force=False, **kw: fake)

    client = TestClient(server.create_app(profile))
    r = client.post("/api/run")
    assert r.json() == {"status": "ok", "date": "2026-06-15"}
    assert (profile.reports_dir / "2026-06-15.html").read_text(encoding="utf-8") == "<div>HI</div>"

    today = client.get("/api/briefing/today").json()
    assert today["status"] == "ok" and today["html"] == "<div>HI</div>"


def test_run_skipped_market_closed(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    fake = RunResult(date="2026-06-13", text="Market closed today...", skipped=True)
    monkeypatch.setattr(main, "run", lambda profile, force=False, **kw: fake)
    client = TestClient(server.create_app(profile))
    body = client.post("/api/run").json()
    assert body["status"] == "skipped" and "closed" in body["message"].lower()


def test_run_error_is_reported_not_raised(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    def boom(profile, force=False, **kw):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(main, "run", boom)
    client = TestClient(server.create_app(profile))
    body = client.post("/api/run").json()
    assert body["status"] == "error" and "yfinance down" in body["message"]


def test_briefing_today_none_when_empty(tmp_path):
    client = TestClient(server.create_app(_profile(tmp_path)))
    assert client.get("/api/briefing/today").json()["status"] == "none"


def test_briefing_today_reads_saved_html_across_restart(tmp_path):
    profile = _profile(tmp_path)
    (profile.reports_dir / "2026-06-14.html").write_text("<div>OLD</div>", encoding="utf-8")
    # fresh app (no in-memory result) -> must read the saved file
    client = TestClient(server.create_app(profile))
    body = client.get("/api/briefing/today").json()
    assert body == {"status": "ok", "date": "2026-06-14", "html": "<div>OLD</div>"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_briefing.py -v`
Expected: FAIL — `POST /api/run` returns 404.

- [ ] **Step 3: Write `src/routes_briefing.py`**

```python
"""Run the pipeline and serve today's briefing.

The engine (main.run) writes reports/<date>.md and returns a RunResult whose .html is
the styled briefing. We persist that html to reports/<date>.html so the Briefing screen
can re-display it after a restart without re-running, and cache the last result in
app.state for the common "just ran it" path.
"""
from __future__ import annotations

from fastapi import Depends

from src import main
from src.deps import get_profile


def _run_and_store(app, profile, force=True):
    result = main.run(profile=profile, force=force)
    if not result.skipped and result.html:
        profile.reports_dir.mkdir(parents=True, exist_ok=True)
        (profile.reports_dir / f"{result.date}.html").write_text(result.html, encoding="utf-8")
    app.state.last_result = result
    return result


def _latest_saved(profile):
    if not profile.reports_dir.exists():
        return None
    files = sorted(profile.reports_dir.glob("*.html"))
    if not files:
        return None
    latest = files[-1]                      # filenames are ISO dates -> lexical == chronological
    return latest.stem, latest.read_text(encoding="utf-8")


def register(app) -> None:
    @app.post("/api/run")
    def run_now(profile=Depends(get_profile)):
        # force=True: a human clicked Run, so produce a briefing even on a closed-market
        # day. The weekend/holiday skip is for the unattended scheduled run (Plan 3).
        try:
            result = _run_and_store(app, profile, force=True)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        if result.skipped:
            return {"status": "skipped", "date": result.date, "message": result.text}
        return {"status": "ok", "date": result.date}

    @app.get("/api/briefing/today")
    def briefing_today(profile=Depends(get_profile)):
        last = app.state.last_result
        if last is not None and not last.skipped and last.html:
            return {"status": "ok", "date": last.date, "html": last.html}
        saved = _latest_saved(profile)
        if saved is None:
            return {"status": "none"}
        date_str, html = saved
        return {"status": "ok", "date": date_str, "html": html}
```

- [ ] **Step 4: Register it in `create_app`**

In `src/server.py`, replace:

```python
    return app
```

with:

```python
    from src import routes_briefing
    routes_briefing.register(app)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_server_briefing.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add src/routes_briefing.py src/server.py tests/test_server_briefing.py
git commit -m "feat: POST /api/run + GET /api/briefing/today with html persistence"
```

---

## Task 8: The browser dashboard (full UI)

Replace the Task 4 stubs with the real four-screen dashboard: Briefing (renders the server HTML, auto-runs on first open per spec Section 8, Run button), Watchlist (ticker chips + settings), Positions (editable table), Integrations (static "coming soon"). Plus the first-run disclaimer modal gated on `/api/state`.

JS behavior is verified manually (Step 5 checklist) — DOM/event logic isn't worth a browser-automation harness for a single-user local app. The automated test asserts the static files are served and contain the expected structure.

**Files:**
- Overwrite: `ui/index.html`, `ui/app.js`, `ui/style.css`
- Test: `tests/test_ui_static.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_static.py`:

```python
from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_index_has_four_screens_and_disclaimer(tmp_path):
    html = _client(tmp_path).get("/").text
    for label in ("Briefing", "Watchlist", "Positions", "Integrations"):
        assert label in html
    assert 'id="disclaimer"' in html
    assert "not financial advice" in html.lower()


def test_appjs_wires_the_api(tmp_path):
    js = _client(tmp_path).get("/app.js").text
    for endpoint in ("/api/state", "/api/briefing/today", "/api/run",
                     "/api/settings", "/api/positions"):
        assert endpoint in js
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_ui_static.py -v`
Expected: FAIL — the stub `index.html` has no nav labels; `app.js` is a comment.

- [ ] **Step 3: Overwrite `ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Advisor</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<div id="disclaimer" class="modal hidden">
  <div class="modal-card">
    <h2>Welcome to Stock Advisor</h2>
    <p>This app provides <b>information, not financial advice</b>. It summarizes public
    market data and rules-based signals to help you do your own research. You are
    responsible for your own investment decisions.</p>
    <button id="accept-btn">I understand &mdash; continue</button>
  </div>
</div>

<header>
  <div class="brand">Stock Advisor</div>
  <nav>
    <button class="nav-btn active" data-screen="briefing">Briefing</button>
    <button class="nav-btn" data-screen="watchlist">Watchlist</button>
    <button class="nav-btn" data-screen="positions">Positions</button>
    <button class="nav-btn" data-screen="integrations">Integrations</button>
  </nav>
</header>

<main>
  <section id="screen-briefing" class="screen">
    <div class="row">
      <h1>Today's briefing</h1>
      <button id="run-btn">Run now</button>
    </div>
    <div id="briefing-status" class="status"></div>
    <div id="briefing-content"></div>
  </section>

  <section id="screen-watchlist" class="screen hidden">
    <h1>Watchlist</h1>
    <div id="ticker-chips" class="chips"></div>
    <div class="row">
      <input id="new-ticker" placeholder="Add ticker (e.g. AAPL)" maxlength="8">
      <button id="add-ticker-btn">Add</button>
    </div>
    <div class="field"><label>Shortlist size
      <input id="shortlist-size" type="number" min="1" max="50"></label></div>
    <div class="field"><label>Lookback days
      <input id="lookback-days" type="number" min="30" max="800"></label></div>
    <button id="save-settings-btn">Save watchlist</button>
    <span id="settings-msg" class="msg"></span>
  </section>

  <section id="screen-positions" class="screen hidden">
    <h1>Positions</h1>
    <table id="positions-table">
      <thead><tr>
        <th>Ticker</th><th>Entry price</th><th>Entry date</th><th>Shares</th><th></th>
      </tr></thead>
      <tbody id="positions-body"></tbody>
    </table>
    <button id="add-position-btn">Add row</button>
    <button id="save-positions-btn">Save positions</button>
    <span id="positions-msg" class="msg"></span>
  </section>

  <section id="screen-integrations" class="screen hidden">
    <h1>Integrations</h1>
    <p class="muted">Optional power features &mdash; coming in a later update.</p>
    <ul class="muted">
      <li><b>AI analysis</b> (bring your own Anthropic key)</li>
      <li><b>Email briefing</b> (bring your own Gmail app password)</li>
    </ul>
    <p class="muted">The app runs fully on rules-based signals without any of these.</p>
  </section>
</main>

<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Overwrite `ui/app.js`**

```javascript
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

// ---- navigation ----
function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
  $(`#screen-${name}`).classList.remove("hidden");
  document.querySelectorAll(".nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.screen === name));
  if (name === "watchlist") loadSettings();
  if (name === "positions") loadPositions();
}
document.querySelectorAll(".nav-btn").forEach((b) =>
  b.addEventListener("click", () => showScreen(b.dataset.screen)));

// ---- briefing ----
async function loadBriefing(autoRun = true) {
  const data = await api("/api/briefing/today");
  if (data.status === "none") {
    if (autoRun) { await runBriefing(); return; }
    $("#briefing-status").textContent = "No briefing yet. Click “Run now”.";
    return;
  }
  $("#briefing-status").textContent = "";
  $("#briefing-content").innerHTML = data.html;   // our own server-rendered HTML
}

async function runBriefing() {
  $("#run-btn").disabled = true;
  $("#briefing-status").textContent = "Running… fetching market data (this can take ~30s).";
  try {
    const r = await api("/api/run", { method: "POST" });
    if (r.status === "ok") { await loadBriefing(false); }
    else if (r.status === "skipped") { $("#briefing-status").textContent = r.message; }
    else { $("#briefing-status").textContent = "Run failed: " + (r.message || "unknown error"); }
  } catch (e) {
    $("#briefing-status").textContent = "Run failed: " + e.message;
  } finally {
    $("#run-btn").disabled = false;
  }
}
$("#run-btn").addEventListener("click", runBriefing);

// ---- watchlist / settings ----
let tickers = [];
function renderChips() {
  $("#ticker-chips").innerHTML = tickers.map((t, i) =>
    `<span class="chip">${esc(t)}<button data-i="${i}" class="chip-x">×</button></span>`).join("");
  document.querySelectorAll(".chip-x").forEach((b) =>
    b.addEventListener("click", () => { tickers.splice(+b.dataset.i, 1); renderChips(); }));
}
async function loadSettings() {
  const data = await api("/api/settings");
  tickers = data.tickers.slice();
  renderChips();
  $("#shortlist-size").value = data.settings.shortlist_size ?? 8;
  $("#lookback-days").value = data.settings.lookback_days ?? 200;
  $("#settings-msg").textContent = "";
}
$("#add-ticker-btn").addEventListener("click", () => {
  const v = $("#new-ticker").value.trim().toUpperCase();
  if (v && !tickers.includes(v)) { tickers.push(v); renderChips(); }
  $("#new-ticker").value = "";
});
$("#save-settings-btn").addEventListener("click", async () => {
  const body = {
    tickers,
    settings: {
      shortlist_size: +$("#shortlist-size").value || 8,
      lookback_days: +$("#lookback-days").value || 200,
    },
  };
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
    $("#settings-msg").textContent = "Saved.";
  } catch (e) { $("#settings-msg").textContent = "Save failed: " + e.message; }
});

// ---- positions ----
function positionRow(p = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML =
    `<td><input class="p-ticker" value="${esc(p.ticker || "")}" maxlength="8"></td>` +
    `<td><input class="p-price" type="number" step="0.01" value="${p.entry_price ?? ""}"></td>` +
    `<td><input class="p-date" type="date" value="${esc(p.entry_date || "")}"></td>` +
    `<td><input class="p-shares" type="number" step="any" value="${p.shares ?? ""}"></td>` +
    `<td><button class="p-del">×</button></td>`;
  tr.querySelector(".p-del").addEventListener("click", () => tr.remove());
  return tr;
}
async function loadPositions() {
  const data = await api("/api/positions");
  const body = $("#positions-body");
  body.innerHTML = "";
  data.positions.forEach((p) => body.appendChild(positionRow(p)));
  $("#positions-msg").textContent = "";
}
$("#add-position-btn").addEventListener("click", () =>
  $("#positions-body").appendChild(positionRow()));
$("#save-positions-btn").addEventListener("click", async () => {
  const positions = [];
  for (const tr of document.querySelectorAll("#positions-body tr")) {
    const ticker = tr.querySelector(".p-ticker").value.trim().toUpperCase();
    const price = parseFloat(tr.querySelector(".p-price").value);
    if (!ticker || !(price > 0)) continue;
    const date = tr.querySelector(".p-date").value.trim();
    const shares = tr.querySelector(".p-shares").value.trim();
    const p = { ticker, entry_price: price };
    if (date) p.entry_date = date;
    if (shares) p.shares = parseFloat(shares);
    positions.push(p);
  }
  try {
    await api("/api/positions", { method: "PUT", body: JSON.stringify({ positions }) });
    $("#positions-msg").textContent = "Saved.";
  } catch (e) { $("#positions-msg").textContent = "Save failed: " + e.message; }
});

// ---- boot ----
async function boot() {
  const state = await api("/api/state");
  if (!state.disclaimer_accepted) {
    $("#disclaimer").classList.remove("hidden");
    $("#accept-btn").addEventListener("click", async () => {
      await api("/api/disclaimer/accept", { method: "POST" });
      $("#disclaimer").classList.add("hidden");
      loadBriefing();
    });
  } else {
    loadBriefing();
  }
}
boot();
```

- [ ] **Step 5: Overwrite `ui/style.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  color: #1f2937; background: #f3f4f6; }
header { display: flex; align-items: center; gap: 24px; padding: 14px 24px;
  background: #0f3d2e; color: #fff; }
.brand { font-weight: 700; font-size: 18px; }
nav { display: flex; gap: 6px; }
.nav-btn { background: transparent; color: #cfe7dd; border: 0; padding: 8px 14px;
  border-radius: 8px; cursor: pointer; font-size: 14px; }
.nav-btn:hover { background: rgba(255, 255, 255, .1); }
.nav-btn.active { background: #fff; color: #0f3d2e; font-weight: 600; }
main { max-width: 640px; margin: 0 auto; padding: 24px; }
.screen h1 { font-size: 20px; margin: 0 0 16px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
button { background: #0f3d2e; color: #fff; border: 0; padding: 9px 16px;
  border-radius: 8px; cursor: pointer; font-size: 14px; }
button:disabled { opacity: .5; cursor: default; }
.status { color: #6b7280; font-size: 13px; margin: 10px 0; }
.msg { margin-left: 10px; color: #047857; font-size: 13px; }
.muted { color: #6b7280; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.chip { background: #e5e7eb; border-radius: 999px; padding: 5px 8px 5px 12px;
  font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }
.chip-x { background: transparent; color: #6b7280; border: 0; padding: 0 2px;
  cursor: pointer; font-size: 15px; }
.field { margin: 10px 0; }
.field input { margin-left: 8px; padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; }
input { font-size: 14px; }
#new-ticker { padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-size: 13px; }
td input { width: 100%; padding: 5px 7px; border: 1px solid #d1d5db; border-radius: 6px; }
.p-del { background: #ef4444; padding: 4px 9px; }
.modal { position: fixed; inset: 0; background: rgba(0, 0, 0, .5);
  display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal-card { background: #fff; border-radius: 12px; padding: 28px; max-width: 420px; }
.modal-card h2 { margin-top: 0; }
.hidden { display: none !important; }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_ui_static.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add ui/ tests/test_ui_static.py
git commit -m "feat: four-screen browser dashboard"
```

---

## Task 9: The launcher (`src/app.py`)

The entry point a packaged install runs: resolve the per-user profile, seed it, find a free port, start uvicorn on `127.0.0.1`, and open the default browser. Factor the testable pieces (`build_profile`, `find_free_port`) out of the blocking `uvicorn.run` call so they can be unit-tested without starting a server.

**Files:**
- Create: `src/app.py`
- Test: `tests/test_app_launcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_launcher.py`:

```python
import socket

from src import app as launcher
from src.profile import Profile


def test_build_profile_uses_user_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_ADVISOR_HOME", str(tmp_path / "home"))
    profile = launcher.build_profile()
    assert isinstance(profile, Profile)
    assert profile.config_dir == tmp_path / "home" / "config"


def test_find_free_port_returns_an_unused_port():
    port = launcher.find_free_port(preferred=8765)
    # nothing should be listening on the returned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        assert s.connect_ex(("127.0.0.1", port)) != 0


def test_find_free_port_skips_a_busy_port():
    # occupy a port, then confirm find_free_port hands back a different one
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        port = launcher.find_free_port(preferred=taken)
        assert port != taken
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app_launcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.app'`.

- [ ] **Step 3: Write `src/app.py`**

```python
"""Launcher / process entry point for the local Stock Advisor app.

`python -m src.app` resolves this machine's profile (%APPDATA%\\StockAdvisor),
seeds first-run defaults, starts the FastAPI server on 127.0.0.1 (loopback only —
never network-exposed), and opens the default browser. The packaged build runs this.
"""
from __future__ import annotations

import socket
import threading
import webbrowser

from src import onboarding, server
from src.apppaths import user_base_dir
from src.profile import Profile

PREFERRED_PORT = 8765


def build_profile() -> Profile:
    return Profile.for_base(user_base_dir())


def find_free_port(preferred: int = PREFERRED_PORT, tries: int = 50) -> int:
    """Return the first free loopback port at or after `preferred`."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:   # nonzero == nothing listening
                return port
    return preferred


def main(open_browser: bool = True) -> None:
    import uvicorn

    profile = build_profile()
    onboarding.seed_profile(profile)
    app = server.create_app(profile)
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Stock Advisor running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app_launcher.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_app_launcher.py
git commit -m "feat: local app launcher (profile + free port + uvicorn + browser)"
```

---

## Task 10: Dependencies, README, full-suite + manual end-to-end verification

Pin the new runtime/test dependencies, document how to launch the app, run the whole suite, then do the one thing the automated tests can't: launch the real app and click through it.

**Files:**
- Modify: `requirements.txt`, `README.md`

- [ ] **Step 1: Add the web dependencies**

Append to `requirements.txt` (after the existing `snaptrade-python-sdk>=11.0` line):

```
fastapi>=0.110
uvicorn>=0.30
httpx>=0.27          # required by fastapi.testclient.TestClient (tests)
```

- [ ] **Step 2: Install them into the venv**

Run: `& .\.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: fastapi, uvicorn, httpx (and their deps: starlette, pydantic, etc.) install with no errors. (If they were already installed during Task 4 Step 3, this is a no-op confirmation.)

- [ ] **Step 3: Run the FULL test suite**

Run: `pytest -q`
Expected: PASS — all pre-existing tests (190+ from Plan 1) plus the new files from Tasks 1–9, with **no network access required** (the server briefing tests monkeypatch `main.run`). If anything fails, fix it before continuing — do not proceed to a manual run on a red suite.

- [ ] **Step 4: Add a README section**

In `README.md`, add a new section (after the existing intro / profile note):

```markdown
## Run the local app (browser dashboard)

The same engine that powers the owner CLI also runs as a small local web app — a
FastAPI server bound to `127.0.0.1` (never network-exposed) plus a plain-HTML
dashboard. Each user's data lives in their own profile dir, **not** in the repo:
`%APPDATA%\StockAdvisor` on Windows (override with the `STOCK_ADVISOR_HOME` env var).

```powershell
& .\.venv\Scripts\Activate.ps1
python -m src.app
```

This seeds a fresh profile from `defaults/` on first run, starts the server on the
first free port at/after 8765, and opens your browser. Screens: **Briefing** (view /
run today's briefing), **Watchlist** (edit tickers + shortlist/lookback), **Positions**
(manual holdings), **Integrations** (optional power features — coming later).
Rules-only by default: no API keys, no cost.
```

- [ ] **Step 5: Manual end-to-end verification**

This confirms the wired-together app (which the unit tests exercise only in pieces) actually works. Use a throwaway profile so your real data is untouched:

```powershell
$env:STOCK_ADVISOR_HOME = "$env:TEMP\StockAdvisorBeta"
& .\.venv\Scripts\Activate.ps1
python -m src.app
```

Confirm, in the browser:
- [ ] The **disclaimer modal** appears on first launch. Click "I understand" — it closes and does not reappear on reload.
- [ ] The **Briefing** screen auto-runs (status shows "Running…") and then renders a styled briefing. (Needs internet for market data; on a closed-market day it shows the "Market closed" message instead — click **Run now** is force-enabled and will still produce one.)
- [ ] **Watchlist:** the seeded tickers appear as chips; add one, remove one, change shortlist size, **Save** → "Saved." Reload the page → changes persisted.
- [ ] **Positions:** add a row (ticker + entry price), **Save** → "Saved." Reload → persisted. Check `%TEMP%\StockAdvisorBeta\config\positions.yaml` reflects it.
- [ ] **Integrations** shows the static "coming soon" panel.
- [ ] Stop the server (Ctrl+C). Confirm **no** `.env`, no personal data, and nothing under the repo's own `config/` or `reports/` changed — all writes went to `%TEMP%\StockAdvisorBeta`.

Then clean up: `Remove-Item -Recurse -Force $env:TEMP\StockAdvisorBeta; Remove-Item Env:\STOCK_ADVISOR_HOME`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt README.md
git commit -m "build: add fastapi/uvicorn/httpx deps + local app docs"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**

*Section 5 (server endpoints):*
- `GET /api/briefing/today` (latest saved or fresh) → Task 7. ✓
- `POST /api/run` (trigger + status) → Task 7. ✓
- `GET/PUT /api/settings` (watchlist) → Task 5. ✓ (weights/exits editing flagged as a non-breaking later extension; bundled defaults are sane — Task 5 note.)
- `GET/PUT /api/positions` → Task 6. ✓
- `PUT /api/secrets` (write-only) → **deferred to Plan 2b** per the owner's decision + spec Section 9 (Integrations is an "optional add-on after the core works"). The `get_profile` seam (Task 4) leaves the secret-store add cleanly insertable. ✓ (scoped)
- Bound to 127.0.0.1 only → Task 9 (`uvicorn.run(host="127.0.0.1")`). ✓

*Section 5 (UI screens):* Briefing, Watchlist, Positions → Task 8; Integrations present as a static "coming soon" panel honoring the four-screen layout → Task 8. ✓
*Section 5 (launcher):* default-browser open + server start → Task 9. ✓

*Section 6 (onboarding):* first-run profile detection + seed bundled defaults → Task 3 (`seed_profile`) + Task 9 (launcher calls it); one-time disclaimer → Task 3 (state) + Task 4 (endpoints) + Task 8 (modal); Integrations as an ignorable page, not a gate → Task 8. ✓

*Section 9 (Beta MVP for this plan):* server + minimal UI (Briefing/Watchlist/Positions/Run) ✓; minimal first-run + disclaimer ✓. PyInstaller/Inno Setup + build-hygiene checklist explicitly **out of scope → Plan 3**.

**Placeholder scan:** No TBD/TODO. Every code step shows complete code; every test shows real assertions; the only "later" references (weights/exits editing, Integrations, packaging) are deliberate scope notes pointing at Plan 2b/Plan 3, not missing implementation. ✓

**Type/name consistency across tasks:** `config.save_watchlist(config_dir, tickers, settings)` / `config.save_positions(config_dir, positions)` (Task 1) are called with those exact signatures in Tasks 5/6. `resources.defaults_dir()` / `resources.ui_dir()` (Task 2) used in Tasks 3/4. `onboarding.seed_profile` / `disclaimer_accepted` / `accept_disclaimer` (Task 3) used in Tasks 4/9. `deps.get_profile` (Task 4) imported by every route module (Tasks 4–7). `server.create_app(profile)` (Task 4) used by every server test and the launcher (Tasks 5–9). Each route module exposes `register(app)` and is wired by editing the unique `    return app` line in `create_app`. `main.run(profile=..., force=...)` and `RunResult` fields match the merged Plan 1 source. ✓

**Engine untouched:** No task modifies `src/main.py` or the scoring/briefing logic — the server consumes `main.run` and `RunResult` as-is, and persists HTML in the server layer. ✓

**Out of scope (later):** `PUT /api/secrets` + Integrations page + OS credential store (Plan 2b); PyInstaller one-folder build, Inno Setup installer, Task Scheduler checkbox, clean-tree build-hygiene checklist (Plan 3, spec Sections 7–8); windowed/pywebview app feel (spec Section 9 optional).
