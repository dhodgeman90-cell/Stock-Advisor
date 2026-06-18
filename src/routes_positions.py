"""Manual positions: GET current, PUT replacement."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config, broker, brokerage_link
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
        # When THIS profile has a linked brokerage, show the SAME live holdings the briefing
        # tracks (live data merged with the per-ticker exit overrides from positions.yaml),
        # tagged live=True so the UI can render the core fields read-only. Otherwise fall back
        # to the manual positions.yaml. Gate on the profile's own creds (not broker.is_configured,
        # which reads global os.environ and isn't profile-scoped); apply_to_environ then makes
        # those creds visible to the fetch in this request.
        if brokerage_link.keys_present(profile.config_dir) and brokerage_link.is_linked(profile.config_dir):
            profile.secrets.apply_to_environ()
            try:
                live = broker.resolve_positions(
                    load_positions=lambda: config.load_positions(profile.config_dir),
                    load_overrides=lambda: config.load_position_overrides(profile.config_dir),
                )
                for p in live:
                    p["live"] = True
                return {"connected": True, "positions": live}
            except Exception:   # noqa: BLE001 - never let a sync hiccup break the tab
                pass
        manual = config.load_positions(profile.config_dir)
        for p in manual:
            p["live"] = False
        return {"connected": False, "positions": manual}

    @app.put("/api/positions")
    def put_positions(body: PositionsBody, profile=Depends(get_profile)):
        # Full replace: positions omitted from the body are removed, and optional
        # per-ticker fields left blank (entry_date, shares, *_pct exit overrides) are
        # dropped. The UI submits the complete positions table on each save.
        try:
            config.save_positions(profile.config_dir,
                                  [p.model_dump() for p in body.positions])
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True}
