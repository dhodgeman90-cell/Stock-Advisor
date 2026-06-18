from fastapi.testclient import TestClient

from src import server, onboarding, briefing, secrets_store, brokerage_link
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
    assert "Send failed" in r.json()["detail"]


def test_put_email_empty_password_clears_it(tmp_path):
    client, _ = _client(tmp_path)
    secrets_store.set_secret("EMAIL_PASSWORD", "old-pw")
    client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com",
        "host": "smtp.gmail.com", "port": "465", "password": "",
    })
    assert secrets_store.has_secret("EMAIL_PASSWORD") is False


def test_put_email_non_numeric_port_is_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com", "host": "smtp.gmail.com", "port": "abc",
    })
    assert r.status_code == 400
    assert "port" in r.json()["detail"].lower()


def test_test_email_502_detail_does_not_echo_exception(tmp_path, monkeypatch):
    from src import briefing
    client, _ = _client(tmp_path)
    client.put("/api/integrations/email", json={
        "user": "me@gmail.com", "to": "me@gmail.com",
        "host": "smtp.gmail.com", "port": "465", "password": "app-pw",
    })

    def boom(*a, **k):
        raise RuntimeError("535 auth failed: app-pw rejected")

    monkeypatch.setattr(briefing, "send_email", boom)
    r = client.post("/api/integrations/email/test")
    assert r.status_code == 502
    assert "app-pw" not in r.json()["detail"]        # raw exception not reflected
    assert "535" not in r.json()["detail"]


def test_integrations_status_includes_brokerage_block(tmp_path):
    client, _ = _client(tmp_path)
    b = client.get("/api/integrations").json()["brokerage"]
    assert b == {"client_id": "", "keys_set": False, "linked": False}


def test_put_brokerage_keys_sets_and_status_reflects(tmp_path):
    client, _ = _client(tmp_path)
    r = client.put("/api/integrations/brokerage/keys",
                   json={"client_id": "cid-1", "consumer_key": "ckey-1"})
    assert r.status_code == 200 and r.json()["keys_set"] is True
    b = client.get("/api/integrations").json()["brokerage"]
    assert b["client_id"] == "cid-1" and b["keys_set"] is True
    assert secrets_store.get_secret("SNAPTRADE_CONSUMER_KEY") == "ckey-1"


def test_brokerage_keys_never_returned(tmp_path):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/brokerage/keys",
               json={"client_id": "cid-1", "consumer_key": "super-secret-key"})
    body = client.get("/api/integrations").json()
    assert "super-secret-key" not in str(body)


def test_connect_returns_portal_url(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/brokerage/keys",
               json={"client_id": "cid-1", "consumer_key": "ckey-1"})
    monkeypatch.setattr(brokerage_link, "start_connect",
                        lambda config_dir, custom_redirect=None: "https://portal.example/go")
    r = client.post("/api/integrations/brokerage/connect")
    assert r.status_code == 200 and r.json()["redirect_url"] == "https://portal.example/go"


def test_connect_passes_local_redirect_to_portal(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    captured = {}

    def fake_start(config_dir, custom_redirect=None):
        captured["redirect"] = custom_redirect
        return "https://portal.example/go"

    monkeypatch.setattr(brokerage_link, "start_connect", fake_start)
    client.post("/api/integrations/brokerage/connect")
    assert captured["redirect"].endswith("/brokerage/connected")


def test_brokerage_connected_landing_page(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/brokerage/connected")
    assert r.status_code == 200
    assert "close this tab" in r.text.lower()


def test_connect_without_keys_is_400(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)

    def boom(config_dir, custom_redirect=None):
        raise brokerage_link.BrokerageError("Enter your SnapTrade Client ID and Consumer Key first.")

    monkeypatch.setattr(brokerage_link, "start_connect", boom)
    r = client.post("/api/integrations/brokerage/connect")
    assert r.status_code == 400
    assert "Client ID" in r.json()["detail"]


def test_verify_reports_connection(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    monkeypatch.setattr(brokerage_link, "check_connection",
                        lambda config_dir: {"connected": True, "account_count": 3})
    r = client.post("/api/integrations/brokerage/verify")
    assert r.status_code == 200 and r.json() == {"connected": True, "account_count": 3}


def test_verify_502_on_transport_error(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)

    def boom(config_dir):
        raise brokerage_link.BrokerageError("Couldn't reach SnapTrade — finish in the browser, then retry.")

    monkeypatch.setattr(brokerage_link, "check_connection", boom)
    r = client.post("/api/integrations/brokerage/verify")
    assert r.status_code == 502
    assert "SnapTrade" in r.json()["detail"]


def test_disconnect_clears(tmp_path):
    client, _ = _client(tmp_path)
    client.put("/api/integrations/brokerage/keys",
               json={"client_id": "cid-1", "consumer_key": "ckey-1"})
    r = client.post("/api/integrations/brokerage/disconnect")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/integrations").json()["brokerage"]["keys_set"] is False
