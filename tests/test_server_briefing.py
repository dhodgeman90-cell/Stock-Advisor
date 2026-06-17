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
    saved = list(profile.reports_dir.glob("2026-06-15_*.html"))   # now timestamped
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "<div>HI</div>"

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


def test_history_lists_newest_first_and_item_fetches(tmp_path):
    profile = _profile(tmp_path)
    profile.reports_dir.mkdir(parents=True, exist_ok=True)
    (profile.reports_dir / "2026-06-16_090000.html").write_text("<p>old</p>", encoding="utf-8")
    (profile.reports_dir / "2026-06-17_090000.html").write_text("<p>am</p>", encoding="utf-8")
    (profile.reports_dir / "2026-06-17_140000.html").write_text("<p>pm</p>", encoding="utf-8")
    client = TestClient(server.create_app(profile))

    items = client.get("/api/briefing/history").json()["items"]
    assert [i["id"] for i in items] == [
        "2026-06-17_140000", "2026-06-17_090000", "2026-06-16_090000"]
    assert items[0]["label"] == "2026-06-17 14:00"

    one = client.get("/api/briefing/item/2026-06-17_090000").json()
    assert one["status"] == "ok" and one["html"] == "<p>am</p>"


def test_item_unknown_or_traversal_not_served(tmp_path):
    profile = _profile(tmp_path)
    client = TestClient(server.create_app(profile))
    # unknown stem -> none (the guard's not-found branch)
    assert client.get("/api/briefing/item/does-not-exist").json()["status"] == "none"
    # traversal attempt -> never returns a briefing (router 404, or guard 'none')
    resp = client.get("/api/briefing/item/..%2f..%2fsecret")
    assert resp.status_code == 404 or resp.json().get("status") != "ok"
