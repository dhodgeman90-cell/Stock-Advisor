from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_serves_ui_shell(tmp_path):
    client = _client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "Stock Advisor" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.js").headers["content-type"].startswith("application/javascript")
    assert client.get("/style.css").status_code == 200
    assert client.get("/style.css").headers["content-type"].startswith("text/css")


def test_disclaimer_flow(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/state").json()["disclaimer_accepted"] is False
    assert client.post("/api/disclaimer/accept").json()["ok"] is True
    assert client.get("/api/state").json()["disclaimer_accepted"] is True
