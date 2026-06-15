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
