from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))


def test_index_has_four_screens_and_disclaimer(tmp_path):
    html = _client(tmp_path).get("/").text
    for label in ("Briefing", "Watchlist", "Positions", "Integrations"):
        assert label in html
    assert 'id="disclaimer"' in html
    assert "not financial advice" in html.lower()


def test_appjs_wires_the_api(tmp_path):
    js = _client(tmp_path).get("/app.js").text
    for endpoint in ("/api/state", "/api/briefing/today", "/api/run",
                     "/api/settings", "/api/positions"):
        assert endpoint in js
