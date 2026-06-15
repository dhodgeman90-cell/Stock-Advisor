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
