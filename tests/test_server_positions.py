from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_get_positions_starts_empty(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/positions").json()["positions"] == []


def test_put_positions_persists(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/positions", json={"positions": [
        {"ticker": "aapl", "entry_price": 150.0, "entry_date": "2026-01-02", "shares": 10},
    ]})
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/api/positions").json()
    assert body["positions"][0]["ticker"] == "AAPL"
    assert body["positions"][0]["entry_price"] == 150.0
    assert body["positions"][0]["entry_date"] == "2026-01-02"
    assert body["positions"][0]["shares"] == 10


def test_put_positions_bad_price_is_400(tmp_path):
    client = _client(tmp_path)
    r = client.put("/api/positions", json={"positions": [
        {"ticker": "X", "entry_price": 0},
    ]})
    assert r.status_code == 400
