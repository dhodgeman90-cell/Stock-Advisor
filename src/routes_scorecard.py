"""Scorecard route: grade how the briefing's past picks actually performed and serve the
rendered result to the UI. Mirrors routes_briefing — one GET, profile-scoped.

The run fetches price history for every distinct ticker (+ SPY), so it can take ~20-40s
the same way a briefing run does; the UI shows a 'grading…' status while it works.
"""
from __future__ import annotations

from fastapi import Depends

from src import scorecard
from src.deps import get_profile


def register(app) -> None:
    @app.get("/api/scorecard")
    def scorecard_view(profile=Depends(get_profile)):
        try:
            result = scorecard.run(profile=profile)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        return {"status": "ok", "date": result.date, "html": result.html}
