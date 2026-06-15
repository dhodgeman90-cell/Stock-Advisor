from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_get_settings_returns_seeded_watchlist(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/settings").json()
    assert "AAPL" in body["tickers"]
    assert body["settings"]["shortlist_size"] == 8


def test_put_settings_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/settings", json={
        "tickers": ["spy", "qqq"],
        "settings": {"shortlist_size": 3, "lookback_days": 120},
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/api/settings").json()
    assert body["tickers"] == ["SPY", "QQQ"]          # upper-cased on save
    assert body["settings"]["shortlist_size"] == 3
    assert body["settings"]["lookback_days"] == 120


def test_put_settings_empty_tickers_is_400(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/settings", json={"tickers": [], "settings": {}})
    assert r.status_code == 400
