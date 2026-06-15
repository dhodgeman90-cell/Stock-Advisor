"""The single 'whose request is this?' seam.

In the local beta the app is started for exactly one Profile, stored on app.state.
In the future hosted product this function becomes the per-tenant auth lookup
(session/token -> tenant profile). Routes depend on it and never change.
"""
from __future__ import annotations

from fastapi import Request

from src.profile import Profile


def get_profile(request: Request) -> Profile:
    return request.app.state.profile
