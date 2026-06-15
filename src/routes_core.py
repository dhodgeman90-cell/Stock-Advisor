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
