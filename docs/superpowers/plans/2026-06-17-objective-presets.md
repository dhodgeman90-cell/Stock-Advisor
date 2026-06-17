# Objective Presets ("Risk Slider") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each user pick an objective preset (Conservative / Balanced / Active / Aggressive Swing) that retunes scoring weights + exit rules and shifts the briefing tone, with in-app briefing history so on-demand runs accumulate instead of overwriting.

**Architecture:** A new `src/objectives.py` holds the four presets as fixed bundles and pure apply-helpers. The active objective is stored per-profile in the existing `app_state.json` (via `onboarding.py`). `main.run` reads it and applies overrides **in-memory** at load time, so the user's YAML stays pristine and `balanced` is the identity preset (no override → today's behavior exactly). The briefing renderers gain an optional tone line. Report HTML is saved with a timestamp so multiple briefings/day coexist, exposed through history endpoints + a UI dropdown and a strategy slider.

**Tech Stack:** Python, FastAPI, pytest, vanilla JS (no build step), PyYAML.

**Deliberate simplification (ponytail):** "Delivery default per objective" from the spec is folded into the tone line + the always-available Run-now/history, rather than building a system that gates email by objective (surprising, and email is already opt-in). Noted here so it's a tracked decision, not an oversight.

---

## File Structure

- **Create** `src/objectives.py` — preset table + pure apply-helpers (`apply_weights`, `apply_exit_rules`, `tone_line`, `options`, `normalize`, `get`). Single source of truth.
- **Create** `tests/test_objectives.py` — unit tests for the helpers.
- **Modify** `src/onboarding.py` — add `get_objective` / `set_objective` reusing `app_state.json`.
- **Modify** `tests/test_onboarding.py` — objective round-trip + default.
- **Modify** `src/main.py` — apply objective to weights + exit rules; pass tone to renderers.
- **Modify** `tests/test_main.py` — objective changes the run's effective config.
- **Modify** `src/briefing.py` — optional `tone_line` param on both renderers.
- **Modify** `tests/test_briefing.py` — tone line present/absent.
- **Modify** `src/routes_settings.py` — `GET/PUT /api/objective`.
- **Modify** `tests/test_server_settings.py` — objective endpoints.
- **Modify** `src/routes_briefing.py` — timestamped storage + history/item endpoints.
- **Modify** `tests/test_server_briefing.py` — multiple runs coexist; history lists; item fetch + traversal guard.
- **Modify** `ui/index.html` + `ui/app.js` — strategy slider + history dropdown.

---

## Task 1: Objective presets module

**Files:**
- Create: `src/objectives.py`
- Test: `tests/test_objectives.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_objectives.py
import pytest
from src import objectives


def test_balanced_is_identity_for_weights():
    base = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    assert objectives.apply_weights(base, "balanced") == base


def test_balanced_is_identity_for_exits():
    base = {"defaults": {"stop_loss_pct": 5, "trailing_stop_pct": 6},
            "backtest": {"buy_threshold": 65, "max_hold_days": 250}}
    out = objectives.apply_exit_rules(base, "balanced")
    assert out == base
    out["defaults"]["stop_loss_pct"] = 99      # mutating the copy must not touch base
    assert base["defaults"]["stop_loss_pct"] == 5


def test_aggressive_overrides_weights_and_exits():
    base_w = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    w = objectives.apply_weights(base_w, "aggressive")
    assert w["trend"] == 10 and w["pullback"] == 0 and w["breakout"] == 35
    base_x = {"defaults": {"stop_loss_pct": 5, "trailing_stop_pct": 6},
              "backtest": {"buy_threshold": 65, "max_hold_days": 250}}
    x = objectives.apply_exit_rules(base_x, "aggressive")
    assert x["defaults"]["stop_loss_pct"] == 4
    assert x["defaults"]["trailing_stop_pct"] == 4
    assert x["backtest"]["buy_threshold"] == 55
    assert x["backtest"]["max_hold_days"] == 30


def test_unknown_key_falls_back_to_balanced():
    base = {"breakout": 30, "volume": 30, "momentum": 20, "trend": 15, "pullback": 5}
    assert objectives.normalize("nonsense") == "balanced"
    assert objectives.apply_weights(base, "nonsense") == base


def test_tone_line_only_for_non_balanced():
    assert objectives.tone_line("balanced") is None
    assert isinstance(objectives.tone_line("conservative"), str)


def test_options_in_slider_order():
    keys = [k for k, _ in objectives.options()]
    assert keys == ["conservative", "balanced", "active", "aggressive"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_objectives.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.objectives'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/objectives.py
"""Objective presets ("risk slider"): named bundles that retune scoring weights and
exit rules without the user editing YAML. Applied in-memory at run time, so the user's
config files stay pristine and switching presets is non-destructive.

`balanced` is the IDENTITY preset — it applies no overrides, so it always reproduces
exactly what the user's weights.yaml / exits.yaml already do. That is the migration
guarantee: existing users default to balanced and see no behavior change.
"""
from __future__ import annotations

import copy

DEFAULT = "balanced"
ORDER = ["conservative", "balanced", "active", "aggressive"]   # slider order

OBJECTIVES = {
    "conservative": {
        "label": "Conservative",
        "weights": {"breakout": 15, "volume": 20, "momentum": 10, "trend": 40, "pullback": 15},
        "stop_loss_pct": 8, "trailing_stop_pct": 12,
        "max_hold_days": 250, "buy_threshold": 75,
        "tone_line": "Conservative lens · trend-led, fewer high-conviction moves, wider stops.",
    },
    "balanced": {
        "label": "Balanced",
        "weights": None,            # identity: use the user's config as-is
        "stop_loss_pct": None, "trailing_stop_pct": None,
        "max_hold_days": None, "buy_threshold": None,
        "tone_line": None,
    },
    "active": {
        "label": "Active",
        "weights": {"breakout": 32, "volume": 30, "momentum": 23, "trend": 12, "pullback": 3},
        "stop_loss_pct": 5, "trailing_stop_pct": 5,
        "max_hold_days": 90, "buy_threshold": 60,
        "tone_line": "Active lens · momentum-tilted with shorter holds.",
    },
    "aggressive": {
        "label": "Aggressive Swing",
        "weights": {"breakout": 35, "volume": 30, "momentum": 25, "trend": 10, "pullback": 0},
        "stop_loss_pct": 4, "trailing_stop_pct": 4,
        "max_hold_days": 30, "buy_threshold": 55,
        "tone_line": "Aggressive Swing lens · momentum-led, tight stops, short holds.",
    },
}


def normalize(key) -> str:
    return key if key in OBJECTIVES else DEFAULT


def get(key) -> dict:
    return OBJECTIVES[normalize(key)]


def apply_weights(base_weights: dict, key) -> dict:
    preset = get(key)
    if preset["weights"] is None:
        return dict(base_weights)
    return {k: float(v) for k, v in preset["weights"].items()}


def apply_exit_rules(base_rules: dict, key) -> dict:
    """Return a deep copy of base_rules with the preset's exit overrides applied.
    Only the four knobs the slider owns are touched; everything else is preserved."""
    preset = get(key)
    rules = copy.deepcopy(base_rules)
    if preset["stop_loss_pct"] is not None:
        rules["defaults"]["stop_loss_pct"] = preset["stop_loss_pct"]
    if preset["trailing_stop_pct"] is not None:
        rules["defaults"]["trailing_stop_pct"] = preset["trailing_stop_pct"]
    if preset["buy_threshold"] is not None:
        rules["backtest"]["buy_threshold"] = preset["buy_threshold"]
    if preset["max_hold_days"] is not None:
        rules["backtest"]["max_hold_days"] = preset["max_hold_days"]
    return rules


def tone_line(key):
    return get(key)["tone_line"]


def options() -> list:
    """[(key, label)] in slider order, for the settings UI."""
    return [(k, OBJECTIVES[k]["label"]) for k in ORDER]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_objectives.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/objectives.py tests/test_objectives.py
git commit -m "feat: objective presets module (weights/exits/tone bundles)"
```

---

## Task 2: Persist the chosen objective per profile

**Files:**
- Modify: `src/onboarding.py`
- Test: `tests/test_onboarding.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_onboarding.py`)

```python
def test_objective_defaults_to_balanced(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    assert onboarding.get_objective(p) == "balanced"


def test_objective_roundtrip_and_preserves_disclaimer(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.accept_disclaimer(p)
    onboarding.set_objective(p, "aggressive")
    assert onboarding.get_objective(p) == "aggressive"
    assert onboarding.disclaimer_accepted(p) is True   # not clobbered


def test_objective_rejects_garbage(tmp_path):
    p = Profile.for_base(tmp_path)
    p.ensure_dirs()
    onboarding.set_objective(p, "nonsense")
    assert onboarding.get_objective(p) == "balanced"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: FAIL — `AttributeError: module 'src.onboarding' has no attribute 'get_objective'`

- [ ] **Step 3: Write minimal implementation** (append to `src/onboarding.py`, after `accept_disclaimer`)

```python
def get_objective(profile) -> str:
    from src import objectives
    return objectives.normalize(_load_state(profile).get("objective"))


def set_objective(profile, key) -> None:
    from src import objectives
    profile.ensure_dirs()
    state = _load_state(profile)
    state["objective"] = objectives.normalize(key)
    _state_path(profile).write_text(json.dumps(state, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_onboarding.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/onboarding.py tests/test_onboarding.py
git commit -m "feat: store objective in per-profile app_state"
```

---

## Task 3: Tone line in the briefing renderers

**Files:**
- Modify: `src/briefing.py` (`render_briefing`, `render_briefing_html`)
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_briefing.py`)

```python
from src import briefing as _b


def _empty_args():
    return dict(ranked=[], vetoed=[], others=[], excluded=[], date_str="2026-06-17",
               regime="neutral", regime_note="steady", holdings=[],
               rotation_plan={}, discovery={})


def test_markdown_tone_line_present_when_set():
    out = _b.render_briefing(**_empty_args(), tone_line="Aggressive lens")
    assert "_Aggressive lens_" in out


def test_markdown_tone_line_absent_by_default():
    out = _b.render_briefing(**_empty_args())
    assert "lens_" not in out


def test_html_tone_line_present_when_set():
    out = _b.render_briefing_html(**_empty_args(), tone_line="Aggressive lens")
    assert "Aggressive lens" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_briefing.py -q`
Expected: FAIL — `TypeError: render_briefing() got an unexpected keyword argument 'tone_line'`

- [ ] **Step 3: Write minimal implementation**

In `src/briefing.py`, change the `render_briefing` signature (line ~138) to add `tone_line=None`:

```python
def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note,
                    holdings=None, rotation_plan=None, discovery=None, tone_line=None) -> str:
```

Replace the header list construction (the `L = [ ... "## Top candidates", ]` block at the top of the function) so the tone line is inserted after the regime line:

```python
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
    ]
    if tone_line:
        L.append(f"_{tone_line}_")
    L += [
        "",
        render_rotation_section(rotation_plan),
        "",
        render_holdings_section(holdings, run_date=date_str),
        "",
        "## Top candidates",
    ]
```

Change the `render_briefing_html` signature (line ~317) to add `tone_line=None`:

```python
def render_briefing_html(ranked, vetoed, others, excluded, date_str, regime,
                         regime_note, holdings=None, rotation_plan=None, discovery=None,
                         tone_line=None) -> str:
```

In `render_briefing_html`, just after `green = "#0f3d2e"`, add:

```python
    tone_html = (f'<div style="font-size:11.5px;color:#cdeede;margin-top:4px;'
                 f'font-style:italic;">{e(tone_line)}</div>') if tone_line else ""
```

and append `{tone_html}` inside the header block — change the header div line to:

```python
        f'<div style="padding:20px 24px;background:{green};color:#ffffff;">'
        f'<div style="font-size:20px;font-weight:700;">Stock Advisor</div>'
        f'<div style="font-size:12.5px;color:#a7d7c5;margin-top:2px;">'
        f'{e(date_str)} &middot; {e(regime)} — {e(regime_note)}</div>{tone_html}</div>',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_briefing.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/briefing.py tests/test_briefing.py
git commit -m "feat: optional tone line in briefing renderers"
```

---

## Task 4: Wire the objective into the run pipeline

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_main.py`)

This test calls `run` with a profile set to `aggressive` and asserts the effective weights/exits the pipeline used differ from balanced. We capture them by monkeypatching `scoring.score_ticker` (receives weights) and `config.load_exit_rules`. Match the existing test style in `tests/test_main.py` for building a profile + fake fetch; if a helper like `_fake_fetch`/`_profile` exists there, reuse it. Otherwise use this self-contained version:

```python
import datetime as dt
import pandas as pd
from src import main, onboarding, scoring
from src.profile import Profile


def _seeded_profile(tmp_path):
    p = Profile.for_base(tmp_path)
    onboarding.seed_profile(p)
    return p


def _fake_fetch(ticker, lookback):
    idx = pd.date_range("2024-01-01", periods=max(lookback, 60), freq="B")
    base = pd.Series(range(len(idx)), index=idx, dtype=float) + 100
    return pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1,
                         "Close": base, "Volume": 1_000_000}, index=idx)


def test_objective_changes_effective_weights(tmp_path, monkeypatch):
    p = _seeded_profile(tmp_path)
    onboarding.set_objective(p, "aggressive")
    seen = {}
    real = scoring.score_ticker
    def spy(df, ticker, weights, settings):
        seen["weights"] = weights
        return real(df, ticker, weights, settings)
    monkeypatch.setattr(scoring, "score_ticker", spy)
    main.run(profile=p, force=True, fetch=_fake_fetch)
    assert seen["weights"]["trend"] == 10        # aggressive preset, not the seeded 15
    assert seen["weights"]["pullback"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -k objective -q`
Expected: FAIL — `assert 15 == 10` (objective not yet applied)

- [ ] **Step 3: Write minimal implementation**

In `src/main.py`, add to the top-level import block (line ~7-9) `objectives` and `onboarding`:

```python
from src import (config, data, scoring, news, agents, adjudicator, briefing,
                 exits, broker, social, congress, insights, market, rotation,
                 objectives, onboarding)
```

After `signals_cfg = config.load_signals(profile.config_dir)` (line ~144), read the objective once:

```python
    objective = onboarding.get_objective(profile)
```

Change the weights load (line ~142) from:

```python
    weights = config.load_weights(profile.config_dir)
```
to:
```python
    weights = objectives.apply_weights(config.load_weights(profile.config_dir), objective)
```

Change the exit-rules load (line ~176) from:

```python
    exit_rules = config.load_exit_rules(profile.config_dir)
```
to:
```python
    exit_rules = objectives.apply_exit_rules(config.load_exit_rules(profile.config_dir), objective)
```

Change both render calls (lines ~329 and ~333) to pass the tone line:

```python
    tone = objectives.tone_line(objective)
    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
    )
    html = briefing.render_briefing_html(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py -k objective -q`
Expected: PASS

- [ ] **Step 5: Run the full main suite to confirm balanced behavior is unchanged**

Run: `python -m pytest tests/test_main.py -q`
Expected: PASS (existing tests use the default/balanced profile → unchanged)

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: apply objective preset to weights, exits, and tone in run"
```

---

## Task 5: Objective settings endpoints

**Files:**
- Modify: `src/routes_settings.py`
- Test: `tests/test_server_settings.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_server_settings.py`)

```python
def test_objective_default_and_options(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/objective").json()
    assert body["objective"] == "balanced"
    keys = [o["key"] for o in body["options"]]
    assert keys == ["conservative", "balanced", "active", "aggressive"]


def test_objective_put_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/objective", json={"objective": "active"})
    assert r.status_code == 200 and r.json()["objective"] == "active"
    assert client.get("/api/objective").json()["objective"] == "active"


def test_objective_put_garbage_falls_back(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/objective", json={"objective": "nope"})
    assert r.json()["objective"] == "balanced"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_settings.py -k objective -q`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Write minimal implementation**

In `src/routes_settings.py`, extend the imports:

```python
from src import config, objectives, onboarding
```

Add a body model near `SettingsBody`:

```python
class ObjectiveBody(BaseModel):
    objective: str
```

Inside `register(app)`, add the two routes:

```python
    @app.get("/api/objective")
    def get_objective(profile=Depends(get_profile)):
        return {
            "objective": onboarding.get_objective(profile),
            "options": [{"key": k, "label": label} for k, label in objectives.options()],
        }

    @app.put("/api/objective")
    def put_objective(body: ObjectiveBody, profile=Depends(get_profile)):
        onboarding.set_objective(profile, body.objective)
        return {"ok": True, "objective": onboarding.get_objective(profile)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_settings.py -k objective -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/routes_settings.py tests/test_server_settings.py
git commit -m "feat: GET/PUT /api/objective endpoints"
```

---

## Task 6: Multiple briefings per day + history

**Files:**
- Modify: `src/routes_briefing.py`
- Test: `tests/test_server_briefing.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_server_briefing.py`)

Match the existing client/fixture style in `tests/test_server_briefing.py`. These tests write report files directly into the profile's `reports_dir` to avoid running the full pipeline:

```python
def test_history_lists_newest_first_and_item_fetches(tmp_path):
    client = _client(tmp_path)                      # existing helper in this file
    profile = client.app.state.profile
    profile.reports_dir.mkdir(parents=True, exist_ok=True)
    (profile.reports_dir / "2026-06-16_090000.html").write_text("<p>old</p>", encoding="utf-8")
    (profile.reports_dir / "2026-06-17_090000.html").write_text("<p>am</p>", encoding="utf-8")
    (profile.reports_dir / "2026-06-17_140000.html").write_text("<p>pm</p>", encoding="utf-8")

    items = client.get("/api/briefing/history").json()["items"]
    assert [i["id"] for i in items] == [
        "2026-06-17_140000", "2026-06-17_090000", "2026-06-16_090000"]
    assert items[0]["label"] == "2026-06-17 14:00"

    one = client.get("/api/briefing/item/2026-06-17_090000").json()
    assert one["status"] == "ok" and one["html"] == "<p>am</p>"


def test_item_rejects_path_traversal(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/briefing/item/..%2f..%2fsecret").json()
    assert r["status"] == "none"
```

If `_client` in this file does not already expose the profile, use `Profile.for_base(tmp_path)` directly as the other server tests do and pass it to `server.create_app`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_briefing.py -k "history or traversal" -q`
Expected: FAIL — 404 (routes not registered)

- [ ] **Step 3: Write minimal implementation**

Rewrite `src/routes_briefing.py` to timestamp saved reports and add history/item routes:

```python
"""Run the pipeline and serve briefings.

main.run writes reports/<date>.md and returns a RunResult whose .html is the styled
briefing. We persist that html to reports/<date>_<HHMMSS>.html so multiple runs in one
day coexist (the Briefing screen's history dropdown lists them), and cache the last
result in app.state for the common "just ran it" path. Filenames are lexically
sortable, so chronological order is free.
"""
from __future__ import annotations

import datetime as dt

from fastapi import Depends

from src import main
from src.deps import get_profile


def _run_and_store(app, profile, force=True):
    result = main.run(profile=profile, force=force)
    if not result.skipped and result.html:
        profile.reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%H%M%S")
        (profile.reports_dir / f"{result.date}_{stamp}.html").write_text(
            result.html, encoding="utf-8")
    app.state.last_result = result
    return result


def _label(stem: str) -> str:
    """'2026-06-17_140322' -> '2026-06-17 14:03'; legacy '2026-06-17' -> '2026-06-17'."""
    if "_" in stem:
        date, t = stem.split("_", 1)
        if len(t) >= 4:
            return f"{date} {t[:2]}:{t[2:4]}"
        return f"{date} {t}"
    return stem


def _latest_saved(profile):
    if not profile.reports_dir.exists():
        return None
    files = sorted(profile.reports_dir.glob("*.html"))
    if not files:
        return None
    latest = files[-1]
    return latest.stem, latest.read_text(encoding="utf-8")


def register(app) -> None:
    @app.post("/api/run")
    def run_now(profile=Depends(get_profile)):
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

    @app.get("/api/briefing/history")
    def briefing_history(profile=Depends(get_profile)):
        if not profile.reports_dir.exists():
            return {"items": []}
        files = sorted(profile.reports_dir.glob("*.html"), reverse=True)
        return {"items": [{"id": f.stem, "label": _label(f.stem)} for f in files]}

    @app.get("/api/briefing/item/{stem}")
    def briefing_item(stem: str, profile=Depends(get_profile)):
        path = profile.reports_dir / f"{stem}.html"
        try:
            path.resolve().relative_to(profile.reports_dir.resolve())
        except ValueError:
            return {"status": "none"}            # path traversal attempt
        if not path.exists():
            return {"status": "none"}
        return {"status": "ok", "id": stem, "label": _label(stem),
                "html": path.read_text(encoding="utf-8")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_briefing.py -q`
Expected: PASS (new + existing tests; `briefing_today` behavior preserved)

- [ ] **Step 5: Commit**

```bash
git add src/routes_briefing.py tests/test_server_briefing.py
git commit -m "feat: timestamped briefings + history/item endpoints"
```

---

## Task 7: UI — strategy slider + history dropdown

**Files:**
- Modify: `ui/index.html`
- Modify: `ui/app.js`

No automated test (vanilla JS, no harness). Verified manually via the `run` skill after the suite is green.

- [ ] **Step 1: Add controls to the briefing screen**

In `ui/index.html`, replace the briefing `<section>` (lines 31-38) with:

```html
  <section id="screen-briefing" class="screen">
    <div class="row">
      <h1>Today's briefing</h1>
      <button id="run-btn">Run now</button>
    </div>
    <div class="field">
      <label>Strategy: <b id="objective-label">Balanced</b></label>
      <input id="objective-slider" type="range" min="0" max="3" step="1" value="1">
    </div>
    <div class="field">
      <label>History
        <select id="briefing-history"></select>
      </label>
    </div>
    <div id="briefing-status" class="status"></div>
    <div id="briefing-content"></div>
  </section>
```

- [ ] **Step 2: Add the objective + history logic to `ui/app.js`**

Add near the top (after the `api` helper), a module-level store for objective options:

```javascript
let objectiveOptions = [];   // [{key,label}] in slider order
```

Add these functions (place them in the briefing section, after `runBriefing`):

```javascript
// ---- objective slider ----
async function loadObjective() {
  const d = await api("/api/objective");
  objectiveOptions = d.options;
  const slider = $("#objective-slider");
  slider.max = String(objectiveOptions.length - 1);
  const idx = objectiveOptions.findIndex((o) => o.key === d.objective);
  slider.value = String(idx < 0 ? 1 : idx);
  $("#objective-label").textContent = objectiveOptions[slider.value]?.label || "Balanced";
}
$("#objective-slider").addEventListener("input", () => {
  const o = objectiveOptions[$("#objective-slider").value];
  if (o) $("#objective-label").textContent = o.label;
});
$("#objective-slider").addEventListener("change", async () => {
  const o = objectiveOptions[$("#objective-slider").value];
  if (!o) return;
  try {
    await api("/api/objective", { method: "PUT", body: JSON.stringify({ objective: o.key }) });
    $("#briefing-status").textContent =
      `Strategy set to ${o.label}. Click “Run now” to generate a briefing with it.`;
  } catch (e) { $("#briefing-status").textContent = "Could not save strategy: " + e.message; }
});

// ---- briefing history ----
async function loadHistory(selectId) {
  const { items } = await api("/api/briefing/history");
  const sel = $("#briefing-history");
  sel.innerHTML = items.map((i) => `<option value="${esc(i.id)}">${esc(i.label)}</option>`).join("");
  if (selectId) sel.value = selectId;
}
$("#briefing-history").addEventListener("change", async () => {
  const id = $("#briefing-history").value;
  if (!id) return;
  const d = await api("/api/briefing/item/" + encodeURIComponent(id));
  if (d.status === "ok") $("#briefing-content").innerHTML = d.html;
});
```

Update `runBriefing`'s success branch so a new run refreshes the history list — change the `if (r.status === "ok")` line to:

```javascript
    if (r.status === "ok") { await loadBriefing(false); await loadHistory(); }
```

Update `boot()` so the objective + history load on startup. Change the `else { loadBriefing(); }` branch and the disclaimer-accept branch to also call the loaders. Replace `boot` with:

```javascript
async function boot() {
  const state = await api("/api/state");
  await loadObjective();
  const start = async () => { await loadBriefing(); await loadHistory(); };
  if (!state.disclaimer_accepted) {
    $("#disclaimer").classList.remove("hidden");
    $("#accept-btn").addEventListener("click", async () => {
      await api("/api/disclaimer/accept", { method: "POST" });
      $("#disclaimer").classList.add("hidden");
      start();
    });
  } else {
    start();
  }
}
boot();
```

- [ ] **Step 3: Run the full test suite (no regressions)**

Run: `python -m pytest -q`
Expected: PASS (all tests, ~279 + new ones)

- [ ] **Step 4: Manual smoke test via the `run` skill**

Launch the local app, confirm: the slider shows "Balanced" and snaps across 4 labels; changing it shows the "Run now" hint; a run produces a briefing; running again adds a second entry to the History dropdown; selecting an older entry swaps the displayed briefing; a non-balanced strategy shows the tone line in the briefing header.

- [ ] **Step 5: Commit**

```bash
git add ui/index.html ui/app.js
git commit -m "feat: strategy slider + briefing history in the UI"
```

---

## Task 8: Backtest validation of the presets (validation, not code)

**Files:** none (uses the existing backtest harness)

- [ ] **Step 1: Run the backtest for each preset and record results**

For each of the four presets, temporarily apply its weights/exits and run the existing backtest entry point (see `src/backtest.py` / `tests/test_backtest.py` for the call signature). Confirm the presets produce **materially different** behavior (turnover, average hold length, max drawdown). A preset indistinguishable from its neighbor should be retuned in `src/objectives.py` (then re-run Task 1 tests).

- [ ] **Step 2: Record the numbers in the spec**

Append a short "Backtest results" table to `docs/superpowers/specs/2026-06-17-objective-presets-design.md` so the chosen values are justified, and commit:

```bash
git add docs/superpowers/specs/2026-06-17-objective-presets-design.md
git commit -m "docs: record objective preset backtest results"
```

---

## Self-Review

**Spec coverage:**
- Objective presets changing selection (weights) + exits → Tasks 1, 4. ✓
- Briefing tone shift → Tasks 3, 4. ✓
- Per-user storage, default balanced, non-destructive → Task 2 (+ identity preset in Task 1). ✓
- Slider UI snapping to named presets → Task 7. ✓
- Multiple briefings/day + history → Task 6, 7. ✓
- In-app primary / email optional → already true; delivery-gating deliberately folded into tone (documented above). ✓
- Backtest each preset → Task 8. ✓
- Migration (balanced == today) → identity preset + Task 4 Step 5 full-suite check. ✓

**Placeholder scan:** No TBD/TODO; every code step shows real code. ✓

**Type consistency:** `apply_weights`/`apply_exit_rules`/`tone_line`/`options`/`normalize`/`get` are defined in Task 1 and used with matching signatures in Tasks 2, 4, 5. `get_objective`/`set_objective` defined in Task 2, used in Tasks 4, 5. Weight keys (`breakout/volume/momentum/trend/pullback`) match `scoring.compute_components`. Exit keys (`defaults.stop_loss_pct`, `defaults.trailing_stop_pct`, `backtest.buy_threshold`, `backtest.max_hold_days`) match `config.load_exit_rules` + `exits.evaluate_exit`. ✓
