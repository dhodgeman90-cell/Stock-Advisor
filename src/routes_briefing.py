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
    latest = files[-1]                      # filenames sort chronologically
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
            return {"status": "none"}            # path-traversal attempt
        if not path.exists():
            return {"status": "none"}
        return {"status": "ok", "id": stem, "label": _label(stem),
                "html": path.read_text(encoding="utf-8")}
