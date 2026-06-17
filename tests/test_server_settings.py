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


def test_objective_default_and_options(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/objective").json()
    assert body["objective"] == "balanced"
    keys = [o["key"] for o in body["options"]]
    assert keys == ["conservative", "balanced", "active", "aggressive"]


def test_objective_put_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/objective", json={"objective": "active"})
    assert r.status_code == 200 and r.json()["objective"] == "active"
    assert client.get("/api/objective").json()["objective"] == "active"


def test_objective_put_garbage_falls_back(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/objective", json={"objective": "nope"})
    assert r.json()["objective"] == "balanced"
