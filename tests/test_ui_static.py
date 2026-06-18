import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import server, onboarding
from src.profile import Profile

_UI = Path(__file__).resolve().parent.parent / "ui"


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


def test_integrations_ui_is_wired(tmp_path):
    client = _client(tmp_path)   # reuse the helper already in this file
    html = client.get("/").text
    assert 'id="ai-key"' in html
    assert 'id="email-user"' in html
    assert 'id="test-email-btn"' in html
    js = client.get("/app.js").text
    assert "/api/integrations" in js
    assert "loadIntegrations" in js


def test_integrations_html_has_brokerage_controls():
    html = (_UI / "index.html").read_text(encoding="utf-8")
    for el in ("snap-client-id", "snap-consumer-key", "connect-broker-btn",
               "check-broker-btn", "disconnect-broker-btn"):
        assert el in html


def test_app_js_wires_brokerage_endpoints():
    js = (_UI / "app.js").read_text(encoding="utf-8")
    assert "/api/integrations/brokerage/keys" in js
    assert "/api/integrations/brokerage/connect" in js
    assert "/api/integrations/brokerage/verify" in js
    assert "/api/integrations/brokerage/disconnect" in js


def test_app_js_is_syntactically_valid():
    """app.js is plain text we serve verbatim, so the test suite never executes it — a
    syntax error (e.g. an unescaped quote) would ship a wholly broken UI silently. Parse
    it with node when available; skip (don't fail) on machines without node installed."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed; cannot syntax-check app.js")
    result = subprocess.run([node, "--check", str(_UI / "app.js")],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"app.js failed node --check:\n{result.stderr}"
