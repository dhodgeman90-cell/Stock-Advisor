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
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True}
