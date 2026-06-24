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
    app.state.last_ping = None     # heartbeat from the UI window; watched by the launcher

    from src import routes_core
    routes_core.register(app)

    from src import routes_settings
    routes_settings.register(app)

    from src import routes_positions
    routes_positions.register(app)

    from src import routes_briefing
    routes_briefing.register(app)

    from src import routes_scorecard
    routes_scorecard.register(app)

    from src import routes_integrations
    routes_integrations.register(app)

    return app
