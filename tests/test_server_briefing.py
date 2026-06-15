from fastapi.testclient import TestClient

from src import server, onboarding, main
from src.profile import Profile
from src.results import RunResult


def _profile(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return profile


def test_run_persists_html_and_caches(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    fake = RunResult(date="2026-06-15", text="t", html="<div>HI</div>", skipped=False,
                     report_path=profile.reports_dir / "2026-06-15.md")
    monkeypatch.setattr(main, "run", lambda profile, force=False, **kw: fake)

    client = TestClient(server.create_app(profile))
    r = client.post("/api/run")
    assert r.json() == {"status": "ok", "date": "2026-06-15"}
    assert (profile.reports_dir / "2026-06-15.html").read_text(encoding="utf-8") == "<div>HI</div>"

    today = client.get("/api/briefing/today").json()
    assert today["status"] == "ok" and today["html"] == "<div>HI</div>"


def test_run_skipped_market_closed(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    fake = RunResult(date="2026-06-13", text="Market closed today...", skipped=True)
    monkeypatch.setattr(main, "run", lambda profile, force=False, **kw: fake)
    client = TestClient(server.create_app(profile))
    body = client.post("/api/run").json()
    assert body["status"] == "skipped" and "closed" in body["message"].lower()


def test_run_error_is_reported_not_raised(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    def boom(profile, force=False, **kw):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(main, "run", boom)
    client = TestClient(server.create_app(profile))
    body = client.post("/api/run").json()
    assert body["status"] == "error" and "yfinance down" in body["message"]


def test_briefing_today_none_when_empty(tmp_path):
    client = TestClient(server.create_app(_profile(tmp_path)))
    assert client.get("/api/briefing/today").json()["status"] == "none"


def test_briefing_today_reads_saved_html_across_restart(tmp_path):
    profile = _profile(tmp_path)
    (profile.reports_dir / "2026-06-14.html").write_text("<div>OLD</div>", encoding="utf-8")
    # fresh app (no in-memory result) -> must read the saved file
    client = TestClient(server.create_app(profile))
    body = client.get("/api/briefing/today").json()
    assert body == {"status": "ok", "date": "2026-06-14", "html": "<div>OLD</div>"}
