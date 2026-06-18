from fastapi.testclient import TestClient

from src import server, onboarding, broker
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_get_positions_starts_empty(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/positions").json()
    assert body["positions"] == []
    assert body["connected"] is False


def test_get_positions_shows_live_holdings_when_connected(tmp_path, monkeypatch):
    from src import brokerage_link, config, secrets_store
    client = _client(tmp_path)
    # mark this profile as linked so the route takes the live path
    config.save_brokerage_identity(tmp_path / "config", client_id="cid", user_id="u")
    secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", "ck")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "us")
    assert brokerage_link.is_linked(tmp_path / "config")
    monkeypatch.setattr(broker, "resolve_positions", lambda **kw: [
        {"ticker": "AAPL", "entry_price": 270.0, "shares": 3, "entry_date": "",
         "stop_loss_pct": 8, "take_profit_pct": None, "trailing_stop_pct": None},
    ])
    body = client.get("/api/positions").json()
    assert body["connected"] is True
    row = body["positions"][0]
    assert row["ticker"] == "AAPL" and row["live"] is True
    assert row["stop_loss_pct"] == 8          # override surfaced for editing


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
