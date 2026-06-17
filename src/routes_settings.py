"""Watchlist settings: GET current, PUT replacement."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config, objectives, onboarding
from src.deps import get_profile


class WatchSettings(BaseModel):
    shortlist_size: int = 8
    lookback_days: int = 200
    min_price: float = 5.0
    min_avg_volume: int = 500000


class SettingsBody(BaseModel):
    tickers: list[str]
    settings: WatchSettings = WatchSettings()


class ObjectiveBody(BaseModel):
    objective: str


def register(app) -> None:
    @app.get("/api/settings")
    def get_settings(profile=Depends(get_profile)):
        wl = config.load_watchlist(profile.config_dir)
        return {"tickers": wl["tickers"], "settings": wl["settings"]}

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, profile=Depends(get_profile)):
        # Full replace, not a merge: any settings key absent from the body resets to
        # its WatchSettings default. The UI always submits the complete settings form,
        # so callers must send every field they want preserved.
        try:
            config.save_watchlist(profile.config_dir, body.tickers,
                                  body.settings.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True}

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
