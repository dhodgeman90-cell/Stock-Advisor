from fastapi.testclient import TestClient

from src import server, onboarding, briefing, secrets_store
from src.profile import Profile


def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile)), profile


def test_status_starts_unset(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/api/integrations").json()
    assert body["ai"]["key_set"] is False
    assert body["email"]["password_set"] is False
    assert body["email"]["host"] == "smtp.gmail.com"   # display default
    assert body["email"]["port"] == "465"


def test_put_ai_sets_and_clears_key(tmp_path):
    client, _ = _client(tmp_path)
    r = client.put("/api/integrations/ai", json={"api_key": "sk-xyz"})
    assert r.status_code == 200 and r.json()["key_set"] is True
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") == "sk-xyz"
    assert client.get("/api/integrations").json()["ai"]["key_set"] is True
    # empty key clears it
    client.put("/api/integrations/ai", json={"api_key": ""})
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False


def test_key_is_never_returned_in_plaintext(tmp_path):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/ai", json={"api_key": "sk-secret"})
    body = client.get("/api/integrations").json()
    assert "sk-secret" not in str(body)   # status only, never the value


def test_put_email_persists_config_and_password(tmp_path):
    client, profile = _client(tmp_path)
    r = client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com",
        "host": "smtp.gmail.com", "port": "465", "password": "app-pw",
    })
    assert r.status_code == 200 and r.json()["password_set"] is True
    body = client.get("/api/integrations").json()["email"]
    assert body["user"] == "me@gmail.com" and body["to"] == "me@gmail.com"
    assert body["password_set"] is True
    assert "app-pw" not in str(body)                       # password never returned
    assert secrets_store.get_secret("EMAIL_PASSWORD") == "app-pw"
    # the live profile reflects the new config without a restart
    assert profile.secrets.get("EMAIL_USER") == "me@gmail.com"


def test_put_email_without_password_keeps_existing(tmp_path):
    client, _ = _client(tmp_path)
    secrets_store.set_secret("EMAIL_PASSWORD", "existing-pw")
    client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com", "host": "smtp.gmail.com", "port": "465",
    })  # password omitted
    assert secrets_store.get_secret("EMAIL_PASSWORD") == "existing-pw"


def test_test_email_400_when_not_configured(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/api/integrations/email/test")
    assert r.status_code == 400
    assert "EMAIL_PASSWORD" in r.json()["detail"]


def test_test_email_sends_with_current_settings(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com",
        "host": "smtp.gmail.com", "port": "465", "password": "app-pw",
    })
    sent = {}

    def fake_send(subject, body, **kw):
        sent.update(kw)
        sent["subject"] = subject

    monkeypatch.setattr(briefing, "send_email", fake_send)
    r = client.post("/api/integrations/email/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert sent["user"] == "me@gmail.com"
    assert sent["password"] == "app-pw"
    assert sent["to_addr"] == "me@gmail.com"
    assert sent["port"] == 465                              # coerced to int


def test_test_email_502_on_send_failure(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com",
        "host": "smtp.gmail.com", "port": "465", "password": "app-pw",
    })

    def boom(*a, **k):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(briefing, "send_email", boom)
    r = client.post("/api/integrations/email/test")
    assert r.status_code == 502
    assert "auth failed" in r.json()["detail"]
