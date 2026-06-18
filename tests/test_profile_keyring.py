import os

from src import secrets_store, config
from src.profile import EnvSecrets, Profile


def test_get_prefers_keyring_then_config_then_env(tmp_path, monkeypatch):
    # .env on disk holds old values; keyring and config hold the live ones and must win.
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=from-dotenv\nEMAIL_TO=from-dotenv\n", encoding="utf-8")
    secrets_store.set_secret("ANTHROPIC_API_KEY", "from-keyring")
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE,
                   config_values={"EMAIL_USER": "me@x.com", "EMAIL_TO": "from-config"})
    assert s.get("ANTHROPIC_API_KEY") == "from-keyring"     # keyring beats .env
    assert s.get("EMAIL_USER") == "me@x.com"                # config layer
    assert s.get("EMAIL_TO") == "from-config"               # config beats .env (same key)
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    assert s.get("EMAIL_HOST") == "smtp.example.com"        # falls through to process env


def test_keyring_only_consulted_for_secret_keys(tmp_path):
    # A non-secret key must not be looked up in the credential store.
    secrets_store.set_secret("EMAIL_USER", "should-be-ignored")  # not a SECRET_KEY
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE,
                   config_values={"EMAIL_USER": "from-config"})
    assert s.get("EMAIL_USER") == "from-config"


def test_apply_to_environ_pushes_keyring_and_config(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_USER", raising=False)
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-live")
    s = EnvSecrets(dotenv_path=tmp_path / "nope.env",
                   keyring_service=secrets_store.SERVICE,
                   config_values={"EMAIL_USER": "me@x.com"})
    s.apply_to_environ()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-live"     # so anthropic.Anthropic() sees it
    assert os.environ["EMAIL_USER"] == "me@x.com"


def test_update_config_values_refreshes_live(tmp_path):
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE, config_values={})
    assert s.get("EMAIL_TO") is None
    s.update_config_values({"EMAIL_TO": "you@x.com"})
    assert s.get("EMAIL_TO") == "you@x.com"


def test_for_repo_does_not_use_keyring(tmp_path):
    # Owner CLI must be untouched: keyring is never consulted for the repo profile.
    secrets_store.set_secret("ANTHROPIC_API_KEY", "leak")
    p = Profile.for_repo()
    # The repo .env may or may not define the key; the point is keyring is NOT a source.
    assert p.secrets._keyring_service is None


def test_for_base_loads_integrations_and_enables_keyring(tmp_path):
    config.save_integrations(tmp_path / "config", user="me@x.com", to="me@x.com",
                             host="smtp.gmail.com", port="465")
    secrets_store.set_secret("EMAIL_PASSWORD", "app-pw")
    p = Profile.for_base(tmp_path)
    assert p.secrets.get("EMAIL_USER") == "me@x.com"        # from integrations.yaml
    assert p.secrets.get("EMAIL_PASSWORD") == "app-pw"      # from keyring


def test_apply_purges_a_cleared_secret_across_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE, config_values={})
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-first")
    s.apply_to_environ()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-first"
    # user clears the key in the UI, then the long-lived server runs again
    secrets_store.delete_secret("ANTHROPIC_API_KEY")
    s.apply_to_environ()
    assert "ANTHROPIC_API_KEY" not in os.environ      # stale value purged
    assert s.get("ANTHROPIC_API_KEY") is None          # gate no longer sees it


def test_apply_overwrites_a_rotated_secret_across_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE, config_values={})
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-old")
    s.apply_to_environ()
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-new")   # rotate
    s.apply_to_environ()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-new"        # SDK sees the new key
    assert s.get("ANTHROPIC_API_KEY") == "sk-new"


def test_apply_leaves_ambient_unowned_managed_var_intact(tmp_path, monkeypatch):
    # A managed-name var present only in the real environment (we never set it) must not
    # be purged: we only remove values THIS instance pushed.
    monkeypatch.setenv("EMAIL_HOST", "ambient.example.com")
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE, config_values={})
    s.apply_to_environ()
    assert os.environ["EMAIL_HOST"] == "ambient.example.com"
    assert s.get("EMAIL_HOST") == "ambient.example.com"


def test_for_repo_apply_is_unchanged_setdefault(tmp_path, monkeypatch):
    # Owner CLI: no managed keys, .env values pushed via setdefault, never clobbering.
    monkeypatch.setenv("OWNER_VAR", "ambient")
    s = EnvSecrets(values={"OWNER_VAR": "from-dotenv", "OTHER": "x"})
    # keyring_service is None here -> nothing is "managed"
    s.apply_to_environ()
    assert os.environ["OWNER_VAR"] == "ambient"   # setdefault did NOT clobber
    assert os.environ["OTHER"] == "x"


def test_profile_exports_all_snaptrade_creds_to_environ(tmp_path, monkeypatch):
    from src import config, secrets_store
    from src.profile import Profile
    for k in ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
              "SNAPTRADE_USER_ID", "SNAPTRADE_USER_SECRET"):
        monkeypatch.delenv(k, raising=False)
    profile = Profile.for_base(tmp_path)
    config.save_brokerage_identity(profile.config_dir, client_id="cid", user_id="uid")
    secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", "ckey")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "usecret")
    # rebuild so the config layer picks up the freshly written integrations.yaml
    profile = Profile.for_base(tmp_path)
    profile.secrets.apply_to_environ()
    import os
    from src import broker
    assert os.environ["SNAPTRADE_CLIENT_ID"] == "cid"
    assert os.environ["SNAPTRADE_CONSUMER_KEY"] == "ckey"
    assert os.environ["SNAPTRADE_USER_ID"] == "uid"
    assert os.environ["SNAPTRADE_USER_SECRET"] == "usecret"
    assert broker.is_configured() is True
