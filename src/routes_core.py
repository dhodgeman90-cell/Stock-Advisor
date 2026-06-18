"""Core routes: serve the static UI, disclaimer state, and the UI heartbeat."""
from __future__ import annotations

import time

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

    @app.get("/brokerage/connected", response_class=HTMLResponse)
    def brokerage_connected():
        # Landing page the SnapTrade portal redirects to after a successful link, so its
        # "Done" button returns somewhere instead of dead-ending. The app window itself
        # detects the connection by polling; this tab is just a friendly dead-end-killer.
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Connected</title></head>"
            "<body style='font-family:system-ui,sans-serif;text-align:center;padding:3rem 1.5rem;color:#14532d'>"
            "<h1 style='font-size:2rem;margin:0 0 .5rem'>&#10003; Connected</h1>"
            "<p style='color:#374151;max-width:28rem;margin:0 auto'>Your brokerage is linked. "
            "You can close this tab and return to Stock Advisor &mdash; your holdings will "
            "appear in the next briefing.</p></body></html>"
        )

    @app.get("/api/state")
    def state(profile=Depends(get_profile)):
        return {"disclaimer_accepted": onboarding.disclaimer_accepted(profile)}

    @app.post("/api/disclaimer/accept")
    def accept(profile=Depends(get_profile)):
        onboarding.accept_disclaimer(profile)
        return {"ok": True}

    @app.get("/api/ping")
    def ping():
        # Heartbeat from the open UI window. The launcher watches app.state.last_ping
        # and shuts the app down once the pings stop (window closed). Monotonic clock
        # so it's immune to wall-clock changes.
        app.state.last_ping = time.monotonic()
        return {"ok": True}
