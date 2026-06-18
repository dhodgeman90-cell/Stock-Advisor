# Connect Robinhood Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Connect Robinhood" button (BYO SnapTrade keys, with guardrails) to the Integrations tab so a new user can link their brokerage from the UI instead of the CLI.

**Architecture:** A new `src/brokerage_link.py` module owns the SnapTrade connect lifecycle (save keys → register user → open portal → verify → disconnect) behind four functions. UI and routes call only those four, so a future SaaS backend swaps the internals without touching anything else. The two SnapTrade secrets live in the OS keyring; the two non-secret identifiers live in `integrations.yaml`. The existing `src/broker.py` still does the holdings sync (with a deprecation fix folded in).

**Tech Stack:** Python, FastAPI, `snaptrade_client` SDK, `keyring`, pytest, vanilla JS frontend.

**Spec:** `docs/superpowers/specs/2026-06-18-connect-robinhood-button-design.md`

**Conventions:**
- Run all commands from the repo root `c:\VS Code\Stock Advisor` with the venv active (`.\.venv\Scripts\Activate.ps1`), or prefix with `.\.venv\Scripts\python.exe -m`.
- Tests use the autouse keyring isolation fixture in `conftest.py`, so `secrets_store` never touches the real credential store.

---

### Task 1: Storage layer — two non-secret SnapTrade fields in `integrations.yaml` + two secret keys in the keyring

**Files:**
- Modify: `src/secrets_store.py:12` (SECRET_KEYS)
- Modify: `src/config.py:215-246` (INTEGRATION_FIELDS, load/save integrations)
- Test: `tests/test_config_integrations.py`, `tests/test_secrets_store.py`

- [ ] **Step 1: Write failing tests for the new brokerage config roundtrip and section isolation**

Add to `tests/test_config_integrations.py`:

```python
def test_save_brokerage_identity_roundtrip(tmp_path):
    config.save_brokerage_identity(tmp_path, client_id="cid-123", user_id="stock-advisor")
    loaded = config.load_integrations(tmp_path)
    assert loaded["SNAPTRADE_CLIENT_ID"] == "cid-123"
    assert loaded["SNAPTRADE_USER_ID"] == "stock-advisor"


def test_brokerage_and_email_coexist_without_clobbering(tmp_path):
    config.save_integrations(tmp_path, user="me@gmail.com", to="me@gmail.com",
                             host="smtp.gmail.com", port="465")
    config.save_brokerage_identity(tmp_path, client_id="cid-123")
    loaded = config.load_integrations(tmp_path)
    assert loaded["EMAIL_USER"] == "me@gmail.com"      # email survived the brokerage write
    assert loaded["SNAPTRADE_CLIENT_ID"] == "cid-123"


def test_save_brokerage_identity_skips_none_clears_blank(tmp_path):
    config.save_brokerage_identity(tmp_path, client_id="cid-123", user_id="u1")
    config.save_brokerage_identity(tmp_path, client_id="")        # client_id cleared, user_id untouched
    loaded = config.load_integrations(tmp_path)
    assert "SNAPTRADE_CLIENT_ID" not in loaded
    assert loaded["SNAPTRADE_USER_ID"] == "u1"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_config_integrations.py -v`
Expected: FAIL with `AttributeError: module 'src.config' has no attribute 'save_brokerage_identity'`

- [ ] **Step 3: Refactor `src/config.py` to support multiple integration sections with merge semantics**

Replace the existing block (from `INTEGRATION_FIELDS = ...` through the end of `save_integrations`, currently `src/config.py:215-246`) with:

```python
INTEGRATION_FIELDS = ("EMAIL_USER", "EMAIL_TO", "EMAIL_HOST", "EMAIL_PORT",
                      "SNAPTRADE_CLIENT_ID", "SNAPTRADE_USER_ID")


def _read_integrations_raw(config_dir) -> dict:
    path = Path(config_dir) / "integrations.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_integrations(config_dir) -> dict:
    """Non-secret integration config from integrations.yaml, keyed by env-var name.

    Secrets (Anthropic key, email app password, SnapTrade consumer key/user secret) are
    NOT here — those live in the OS credential store (see src/secrets_store.py). A
    missing/blank file yields {}.
    """
    data = _read_integrations_raw(config_dir)
    out = {}
    email = data.get("email") or {}
    for env_key, yaml_key in (("EMAIL_USER", "user"), ("EMAIL_TO", "to"),
                              ("EMAIL_HOST", "host"), ("EMAIL_PORT", "port")):
        val = email.get(yaml_key)
        if val is not None and str(val).strip() != "":
            out[env_key] = str(val).strip()
    brokerage = data.get("brokerage") or {}
    for env_key, yaml_key in (("SNAPTRADE_CLIENT_ID", "client_id"),
                              ("SNAPTRADE_USER_ID", "user_id")):
        val = brokerage.get(yaml_key)
        if val is not None and str(val).strip() != "":
            out[env_key] = str(val).strip()
    return out


def _write_integration_section(config_dir, section: str, mapping: dict) -> None:
    """Merge `mapping` into one section of integrations.yaml, preserving other sections.

    A value of None means "leave unchanged"; "" (or blank) means "clear that field";
    any other value is set (stringified + trimmed). Blank fields are never written as
    empty strings, which the engine would misread as 'configured'.
    """
    data = _read_integrations_raw(config_dir)
    sect = dict(data.get(section) or {})
    for key, val in mapping.items():
        if val is None:
            continue
        sval = str(val).strip()
        if sval == "":
            sect.pop(key, None)
        else:
            sect[key] = sval
    if sect:
        data[section] = sect
    else:
        data.pop(section, None)
    _atomic_write_yaml(Path(config_dir) / "integrations.yaml", data)


def save_integrations(config_dir, *, user="", to="", host="", port="") -> None:
    """Persist non-secret email config to the 'email' section of integrations.yaml."""
    _write_integration_section(config_dir, "email",
                               {"user": user, "to": to, "host": host, "port": port})


def save_brokerage_identity(config_dir, *, client_id=None, user_id=None) -> None:
    """Persist the non-secret SnapTrade identifiers to the 'brokerage' section.

    Pass None to leave a field unchanged, "" to clear it. The secret consumer key and
    user secret are stored separately in the OS keyring, not here."""
    _write_integration_section(config_dir, "brokerage",
                               {"client_id": client_id, "user_id": user_id})
```

- [ ] **Step 4: Run the config tests (new + existing) to verify they pass**

Run: `pytest tests/test_config_integrations.py -v`
Expected: PASS (all, including the pre-existing email roundtrip tests)

- [ ] **Step 5: Add the two SnapTrade secrets to the keyring's managed key set**

In `src/secrets_store.py:12`, change:

```python
SECRET_KEYS = ("ANTHROPIC_API_KEY", "EMAIL_PASSWORD")
```
to:
```python
SECRET_KEYS = ("ANTHROPIC_API_KEY", "EMAIL_PASSWORD",
               "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_USER_SECRET")
```

- [ ] **Step 6: Write a failing test that the per-user profile exports all four SnapTrade vars to the environment**

Add to `tests/test_profile_keyring.py`:

```python
def test_profile_exports_all_snaptrade_creds_to_environ(tmp_path, monkeypatch):
    from src import config, secrets_store
    from src.profile import Profile
    for k in ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
              "SNAPTRADE_USER_ID", "SNAPTRADE_USER_SECRET"):
        monkeypatch.delenv(k, raising=False)
    profile = Profile.for_base(tmp_path)
    config.save_brokerage_identity(tmp_path, client_id="cid", user_id="uid")
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
```

- [ ] **Step 7: Run it to verify it passes**

Run: `pytest tests/test_profile_keyring.py::test_profile_exports_all_snaptrade_creds_to_environ -v`
Expected: PASS (no production change needed beyond Steps 3 & 5 — `apply_to_environ` already exports `SECRET_KEYS` + `INTEGRATION_FIELDS`). If it fails, the cause is in Step 3 or 5; fix there.

- [ ] **Step 8: Commit**

```bash
git add src/config.py src/secrets_store.py tests/test_config_integrations.py tests/test_profile_keyring.py
git commit -m "feat: store SnapTrade keys (keyring secrets + integrations.yaml identifiers)"
```

---

### Task 2: `brokerage_link.py` — the connect lifecycle seam

**Files:**
- Create: `src/brokerage_link.py`
- Test: `tests/test_brokerage_link.py` (create)
- Modify: `tests/fakes.py` (extend `FakeSnapTrade` with authentication + holdings)

- [ ] **Step 1: Extend the SnapTrade fake with authentication and holdings**

In `tests/fakes.py`, replace `_FakeAccountInfo` and `FakeSnapTrade` (currently `tests/fakes.py:25-43`) with:

```python
class _FakeAccountInfo:
    def __init__(self, accounts, positions_by_account):
        self._accounts = accounts
        self._positions_by_account = positions_by_account
        self.positions_calls = []   # account_ids queried, in order

    def list_user_accounts(self, user_id=None, user_secret=None):
        return _Resp(list(self._accounts))

    def get_user_holdings(self, user_id=None, user_secret=None, account_id=None):
        self.positions_calls.append(account_id)
        return _Resp({"positions": list(self._positions_by_account.get(account_id, []))})


class _FakeAuth:
    def __init__(self, user_secret="usecret", redirect_uri="https://app.snaptrade.com/portal"):
        self._user_secret = user_secret
        self._redirect_uri = redirect_uri
        self.registered = []   # user_ids passed to register, in order

    def register_snap_trade_user(self, user_id=None):
        self.registered.append(user_id)
        return _Resp({"userId": user_id, "userSecret": self._user_secret})

    def login_snap_trade_user(self, user_id=None, user_secret=None):
        return _Resp({"redirectURI": self._redirect_uri})


class FakeSnapTrade:
    """Minimal SnapTrade SDK stand-in serving canned accounts, holdings, and auth."""

    def __init__(self, accounts=None, positions_by_account=None,
                 user_secret="usecret", redirect_uri="https://app.snaptrade.com/portal"):
        self.account_information = _FakeAccountInfo(accounts or [], positions_by_account or {})
        self.authentication = _FakeAuth(user_secret, redirect_uri)
```

- [ ] **Step 2: Write failing tests for `brokerage_link`**

Create `tests/test_brokerage_link.py`:

```python
import pytest

from src import brokerage_link, config, secrets_store
from tests.fakes import FakeSnapTrade


def test_save_keys_persists_client_id_and_consumer_key(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    assert config.load_integrations(tmp_path)["SNAPTRADE_CLIENT_ID"] == "cid-1"
    assert secrets_store.get_secret("SNAPTRADE_CONSUMER_KEY") == "ckey-1"
    assert brokerage_link.keys_present(tmp_path) is True


def test_save_keys_blank_consumer_key_clears_it(tmp_path):
    secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", "old")
    brokerage_link.save_keys(tmp_path, "cid-1", "")
    assert secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY") is False


def test_start_connect_requires_keys(tmp_path):
    with pytest.raises(brokerage_link.BrokerageError):
        brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: FakeSnapTrade())


def test_start_connect_registers_user_then_returns_portal_url(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    fake = FakeSnapTrade(user_secret="us-xyz", redirect_uri="https://portal.example/abc")
    url = brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: fake)
    assert url == "https://portal.example/abc"
    assert fake.authentication.registered == ["stock-advisor"]      # registered once
    assert config.load_integrations(tmp_path)["SNAPTRADE_USER_ID"] == "stock-advisor"
    assert secrets_store.get_secret("SNAPTRADE_USER_SECRET") == "us-xyz"


def test_start_connect_reuses_existing_user_without_reregistering(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="existing-user")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "existing-secret")
    fake = FakeSnapTrade(redirect_uri="https://portal.example/reuse")
    url = brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: fake)
    assert url == "https://portal.example/reuse"
    assert fake.authentication.registered == []                    # no re-registration


def test_check_connection_reports_account_count(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    fake = FakeSnapTrade(accounts=[{"id": "a"}, {"id": "b"}])
    status = brokerage_link.check_connection(tmp_path, client_factory=lambda c, k: fake)
    assert status == {"connected": True, "account_count": 2}


def test_check_connection_false_when_not_linked(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")   # keys but never connected
    status = brokerage_link.check_connection(tmp_path, client_factory=lambda c, k: FakeSnapTrade())
    assert status == {"connected": False, "account_count": 0}


def test_is_linked_true_only_after_connect(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    assert brokerage_link.is_linked(tmp_path) is False
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    assert brokerage_link.is_linked(tmp_path) is True


def test_disconnect_clears_everything(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    brokerage_link.disconnect(tmp_path)
    ic = config.load_integrations(tmp_path)
    assert "SNAPTRADE_CLIENT_ID" not in ic and "SNAPTRADE_USER_ID" not in ic
    assert secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY") is False
    assert secrets_store.has_secret("SNAPTRADE_USER_SECRET") is False


def test_start_connect_maps_sdk_error_to_brokerage_error(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")

    class Boom(FakeSnapTrade):
        def __init__(self):
            super().__init__()
            class _A:
                def register_snap_trade_user(self, user_id=None):
                    raise RuntimeError("401 unauthorized")
            self.authentication = _A()

    with pytest.raises(brokerage_link.BrokerageError):
        brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: Boom())
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_brokerage_link.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.brokerage_link'`

- [ ] **Step 4: Implement `src/brokerage_link.py`**

Create `src/brokerage_link.py`:

```python
"""Connect a brokerage (Robinhood) to Stock Advisor via SnapTrade — the lifecycle seam.

The UI and routes call ONLY the four lifecycle functions here (save_keys, start_connect,
check_connection, disconnect) plus the two cheap status helpers (keys_present, is_linked).
Today these talk to SnapTrade directly using the user's own (BYO) app keys. A future SaaS
build implements the same surface against a hosted backend that holds the consumer key —
the routes and UI never change. See the spec for the upgrade path.

Read-only: this module establishes the link and reads account presence; it never trades.
"""
from __future__ import annotations

from src import config, secrets_store

USER_ID_DEFAULT = "stock-advisor"


class BrokerageError(Exception):
    """A user-facing brokerage-link failure (bad keys, portal unavailable, etc.)."""


def _client(client_id, consumer_key):
    from snaptrade_client import SnapTrade
    return SnapTrade(consumer_key=consumer_key, client_id=client_id)


def _field(body, *names):
    """Read a field from an SDK response body that may be a dict, frozendict, or object."""
    for name in names:
        try:
            if name in body:
                return body[name]
        except TypeError:
            pass
        if hasattr(body, name):
            return getattr(body, name)
    return None


def _creds(config_dir):
    ic = config.load_integrations(config_dir)
    return (
        ic.get("SNAPTRADE_CLIENT_ID"),
        secrets_store.get_secret("SNAPTRADE_CONSUMER_KEY"),
        ic.get("SNAPTRADE_USER_ID"),
        secrets_store.get_secret("SNAPTRADE_USER_SECRET"),
    )


def keys_present(config_dir) -> bool:
    """True when both app keys (client id + consumer key) are stored."""
    client_id = config.load_integrations(config_dir).get("SNAPTRADE_CLIENT_ID")
    return bool(client_id) and secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY")


def is_linked(config_dir) -> bool:
    """True when a connected user has been registered (user id + secret stored)."""
    user_id = config.load_integrations(config_dir).get("SNAPTRADE_USER_ID")
    return bool(user_id) and secrets_store.has_secret("SNAPTRADE_USER_SECRET")


def save_keys(config_dir, client_id, consumer_key) -> None:
    """Persist the user's SnapTrade app keys (client id -> config, consumer key -> keyring)."""
    config.save_brokerage_identity(config_dir, client_id=(client_id or "").strip())
    ck = (consumer_key or "").strip()
    if ck:
        secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", ck)
    else:
        secrets_store.delete_secret("SNAPTRADE_CONSUMER_KEY")


def start_connect(config_dir, *, client_factory=_client) -> str:
    """Register the connected user (once) and return the SnapTrade portal URL to open."""
    client_id, consumer_key, user_id, user_secret = _creds(config_dir)
    if not client_id or not consumer_key:
        raise BrokerageError("Enter your SnapTrade Client ID and Consumer Key first.")
    client = client_factory(client_id, consumer_key)

    if not user_id or not user_secret:
        user_id = user_id or USER_ID_DEFAULT
        try:
            resp = client.authentication.register_snap_trade_user(user_id=user_id)
            user_secret = _field(resp.body, "userSecret", "user_secret")
        except Exception as e:   # noqa: BLE001 - surface a friendly message, not the SDK trace
            raise BrokerageError(
                "Could not register with SnapTrade — double-check your keys. "
                "Note the free tier allows 5 connections."
            ) from e
        if not user_secret:
            raise BrokerageError("Registration returned no user secret — check your keys.")
        config.save_brokerage_identity(config_dir, user_id=user_id)
        secrets_store.set_secret("SNAPTRADE_USER_SECRET", user_secret)

    try:
        resp = client.authentication.login_snap_trade_user(user_id=user_id, user_secret=user_secret)
        url = _field(resp.body, "redirectURI", "redirect_uri")
    except Exception as e:   # noqa: BLE001
        raise BrokerageError("Could not open the SnapTrade portal — try again in a moment.") from e
    if not url:
        raise BrokerageError("Could not open the SnapTrade portal — try again in a moment.")
    return url


def check_connection(config_dir, *, client_factory=_client) -> dict:
    """Poll SnapTrade for linked accounts. Returns {connected, account_count}.

    Raises BrokerageError on a transport/credential failure so the route can return 502;
    'no accounts yet' is NOT an error — it returns connected=False.
    """
    client_id, consumer_key, user_id, user_secret = _creds(config_dir)
    if not all([client_id, consumer_key, user_id, user_secret]):
        return {"connected": False, "account_count": 0}
    client = client_factory(client_id, consumer_key)
    try:
        resp = client.account_information.list_user_accounts(
            user_id=user_id, user_secret=user_secret)
        accounts = list(resp.body) if resp.body else []
    except Exception as e:   # noqa: BLE001
        raise BrokerageError("Couldn't reach SnapTrade — finish in the browser, then retry.") from e
    return {"connected": len(accounts) > 0, "account_count": len(accounts)}


def disconnect(config_dir) -> None:
    """Clear all stored brokerage credentials (both secrets and both identifiers)."""
    config.save_brokerage_identity(config_dir, client_id="", user_id="")
    secrets_store.delete_secret("SNAPTRADE_CONSUMER_KEY")
    secrets_store.delete_secret("SNAPTRADE_USER_SECRET")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_brokerage_link.py tests/test_broker.py -v`
Expected: PASS for `test_brokerage_link.py`. `test_broker.py` will FAIL here (the fake now exposes `get_user_holdings` instead of `get_user_account_positions`) — that is fixed in Task 4. If you are running tasks in order, expect the broker failures and proceed to Task 4; do not "fix" them in this task.

- [ ] **Step 6: Commit**

```bash
git add src/brokerage_link.py tests/test_brokerage_link.py tests/fakes.py
git commit -m "feat: brokerage_link module for the SnapTrade connect lifecycle"
```

---

### Task 3: API routes — brokerage endpoints in the Integrations router

**Files:**
- Modify: `src/routes_integrations.py`
- Test: `tests/test_server_integrations.py`

- [ ] **Step 1: Write failing route tests**

Add to `tests/test_server_integrations.py` (note: these tests patch `brokerage_link` on the route module so no network is hit):

```python
from src import brokerage_link


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
                        lambda config_dir: "https://portal.example/go")
    r = client.post("/api/integrations/brokerage/connect")
    assert r.status_code == 200 and r.json()["redirect_url"] == "https://portal.example/go"


def test_connect_without_keys_is_400(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)

    def boom(config_dir):
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_server_integrations.py -v -k brokerage`
Expected: FAIL — `KeyError: 'brokerage'` / 404 on the new endpoints.

- [ ] **Step 3: Implement the routes**

In `src/routes_integrations.py`, add to the imports line (currently `from src import config, secrets_store, briefing`):

```python
from src import config, secrets_store, briefing, brokerage_link
```

Add a request model next to the existing `EmailBody` (after `src/routes_integrations.py:31`):

```python
class BrokerageKeysBody(BaseModel):
    client_id: str = ""
    consumer_key: str = ""      # "" clears the stored consumer key
```

In `get_integrations` (the `GET /api/integrations` handler), add a `brokerage` key to the returned dict:

```python
        ic = config.load_integrations(profile.config_dir)
        return {
            "ai": {"key_set": secrets_store.has_secret("ANTHROPIC_API_KEY")},
            "email": {
                "user": ic.get("EMAIL_USER", ""),
                "to": ic.get("EMAIL_TO", ""),
                "host": ic.get("EMAIL_HOST", "smtp.gmail.com"),
                "port": ic.get("EMAIL_PORT", "465"),
                "password_set": secrets_store.has_secret("EMAIL_PASSWORD"),
            },
            "brokerage": {
                "client_id": ic.get("SNAPTRADE_CLIENT_ID", ""),
                "keys_set": brokerage_link.keys_present(profile.config_dir),
                "linked": brokerage_link.is_linked(profile.config_dir),
            },
        }
```

Add these four handlers inside `register(app)` (after the existing email handlers):

```python
    @app.put("/api/integrations/brokerage/keys")
    def put_brokerage_keys(body: BrokerageKeysBody, profile=Depends(get_profile)):
        brokerage_link.save_keys(profile.config_dir, body.client_id, body.consumer_key)
        # Refresh the live profile so a connect/run in this session sees the new keys.
        profile.secrets.update_config_values(config.load_integrations(profile.config_dir))
        return {"ok": True, "keys_set": brokerage_link.keys_present(profile.config_dir)}

    @app.post("/api/integrations/brokerage/connect")
    def connect_brokerage(profile=Depends(get_profile)):
        try:
            url = brokerage_link.start_connect(profile.config_dir)
        except brokerage_link.BrokerageError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        profile.secrets.update_config_values(config.load_integrations(profile.config_dir))
        return {"redirect_url": url}

    @app.post("/api/integrations/brokerage/verify")
    def verify_brokerage(profile=Depends(get_profile)):
        try:
            return brokerage_link.check_connection(profile.config_dir)
        except brokerage_link.BrokerageError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @app.post("/api/integrations/brokerage/disconnect")
    def disconnect_brokerage(profile=Depends(get_profile)):
        brokerage_link.disconnect(profile.config_dir)
        profile.secrets.update_config_values(config.load_integrations(profile.config_dir))
        return {"ok": True}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_server_integrations.py -v`
Expected: PASS (new brokerage tests + all pre-existing email/ai tests)

- [ ] **Step 5: Commit**

```bash
git add src/routes_integrations.py tests/test_server_integrations.py
git commit -m "feat: brokerage connect/verify/disconnect API endpoints"
```

---

### Task 4: Fix the deprecated holdings call in `broker.py`

**Files:**
- Modify: `src/broker.py:50-56` (`_default_list_positions`)
- Test: `tests/test_broker.py` (already exercises this path via `fetch_holdings`; the fake was updated in Task 2)

- [ ] **Step 1: Run the broker tests to confirm they currently fail against the updated fake**

Run: `pytest tests/test_broker.py -v`
Expected: FAIL — `AttributeError: '_FakeAccountInfo' object has no attribute 'get_user_account_positions'` (the fake now exposes `get_user_holdings`).

- [ ] **Step 2: Update `_default_list_positions` to the non-deprecated holdings endpoint**

In `src/broker.py`, replace `_default_list_positions` (currently `src/broker.py:50-56`):

```python
def _default_list_positions(client, account_id) -> list:
    resp = client.account_information.get_user_account_positions(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
        account_id=account_id,
    )
    return list(resp.body)
```
with:
```python
def _default_list_positions(client, account_id) -> list:
    # get_user_holdings replaces the deprecated get_user_account_positions; its body is a
    # holdings object whose `positions` array has the same per-position shape we parse.
    resp = client.account_information.get_user_holdings(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
        account_id=account_id,
    )
    body = resp.body or {}
    positions = body["positions"] if "positions" in body else []
    return list(positions)
```

- [ ] **Step 3: Run the broker tests to verify they pass**

Run: `pytest tests/test_broker.py -v`
Expected: PASS (all four `fetch_holdings` tests, including the pinned-account `positions_calls` assertion)

- [ ] **Step 4: Commit**

```bash
git add src/broker.py
git commit -m "fix: use non-deprecated SnapTrade get_user_holdings for positions"
```

---

### Task 5: UI — the "Brokerage (Robinhood)" section in the Integrations tab

**Files:**
- Modify: `ui/index.html:77-113` (Integrations section)
- Modify: `ui/app.js:176-225` (integrations handlers)
- Test: `tests/test_ui_static.py` (asserts key UI elements ship; see Step 4)

- [ ] **Step 1: Add the Brokerage block to `ui/index.html`**

In `ui/index.html`, insert this block inside `<section id="screen-integrations">`, immediately before the closing `</section>` (i.e., after the email block's `<span id="integrations-msg" class="msg"></span>` at `ui/index.html:112`):

```html
    <h2>Brokerage (Robinhood)</h2>
    <p class="muted">Connect your brokerage to sync your real holdings into the briefing.
    The connection is <b>read-only</b> &mdash; this app can never place trades &mdash; and your
    brokerage password is never stored here. You log in once through SnapTrade (which handles
    2-step verification), and daily briefings sync automatically after that.</p>
    <p class="muted">For now you bring your own free SnapTrade keys (a one-time, ~3-minute setup).
    This keeps your connection private to your own computer. A simpler one-click option may come
    later.</p>
    <details class="howto">
      <summary>How to get your free SnapTrade keys</summary>
      <ol>
        <li>Create a free account at
          <a href="https://dashboard.snaptrade.com" target="_blank" rel="noopener">dashboard.snaptrade.com</a>.</li>
        <li>Create an app/project in the dashboard.</li>
        <li>Copy the <b>Client ID</b> and <b>Consumer Key</b> it gives you.</li>
        <li>Paste them below and click <b>Save keys</b>, then <b>Connect Robinhood</b>.</li>
      </ol>
    </details>
    <div class="field"><label>SnapTrade Client ID
      <input id="snap-client-id" type="text" placeholder="e.g. STOCKADVISOR-ABCD" autocomplete="off"></label></div>
    <div class="field"><label>SnapTrade Consumer Key
      <input id="snap-consumer-key" type="password" placeholder="leave blank to keep current" autocomplete="off"></label></div>
    <span id="snap-keys-status" class="muted"></span>
    <div class="row">
      <button id="save-snap-keys-btn">Save keys</button>
    </div>
    <div class="row">
      <button id="connect-broker-btn">Connect Robinhood</button>
      <button id="check-broker-btn">Check connection</button>
      <button id="disconnect-broker-btn">Disconnect</button>
    </div>
    <span id="broker-status" class="muted"></span>
```

- [ ] **Step 2: Wire up the handlers in `ui/app.js`**

In `ui/app.js`, extend `loadIntegrations()` (currently `ui/app.js:177-188`) by adding these lines before its closing brace (before `$("#integrations-msg").textContent = "";`):

```javascript
  $("#snap-client-id").value = d.brokerage.client_id || "";
  $("#snap-consumer-key").value = "";
  $("#snap-keys-status").textContent = d.brokerage.keys_set ? "Keys saved ✓" : "No keys set.";
  $("#broker-status").textContent = d.brokerage.linked
    ? "Previously connected — click “Check connection” to confirm." : "Not connected.";
```

Then add these handlers after the `test-email-btn` handler (after `ui/app.js:225`):

```javascript
$("#save-snap-keys-btn").addEventListener("click", async () => {
  const body = {
    client_id: $("#snap-client-id").value.trim(),
    consumer_key: $("#snap-consumer-key").value,   // blank keeps existing
  };
  try {
    await api("/api/integrations/brokerage/keys", { method: "PUT", body: JSON.stringify(body) });
    $("#integrations-msg").textContent = "Brokerage keys saved.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Save failed: " + e.message; }
});

let brokerPoll = null;
async function checkBroker(quiet) {
  try {
    const d = await api("/api/integrations/brokerage/verify", { method: "POST" });
    if (d.connected) {
      $("#broker-status").textContent = `Connected ✓ — ${d.account_count} account(s).`;
      if (brokerPoll) { clearInterval(brokerPoll); brokerPoll = null; }
    } else if (!quiet) {
      $("#broker-status").textContent = "Not connected yet — finish logging in, then Check connection.";
    }
  } catch (e) {
    if (!quiet) $("#broker-status").textContent = "Check failed: " + e.message;
  }
}
$("#connect-broker-btn").addEventListener("click", async () => {
  $("#broker-status").textContent = "Opening SnapTrade…";
  try {
    const d = await api("/api/integrations/brokerage/connect", { method: "POST" });
    window.open(d.redirect_url, "_blank", "noopener");
    $("#broker-status").textContent = "Finish logging in to Robinhood in the new tab…";
    // Auto-poll for ~60s so the status flips to Connected without the user clicking.
    if (brokerPoll) clearInterval(brokerPoll);
    let ticks = 0;
    brokerPoll = setInterval(() => {
      if (++ticks > 20) { clearInterval(brokerPoll); brokerPoll = null; return; }
      checkBroker(true);
    }, 3000);
  } catch (e) { $("#broker-status").textContent = "Connect failed: " + e.message; }
});
$("#check-broker-btn").addEventListener("click", () => checkBroker(false));
$("#disconnect-broker-btn").addEventListener("click", async () => {
  try {
    await api("/api/integrations/brokerage/disconnect", { method: "POST" });
    if (brokerPoll) { clearInterval(brokerPoll); brokerPoll = null; }
    $("#integrations-msg").textContent = "Brokerage disconnected.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Disconnect failed: " + e.message; }
});
```

- [ ] **Step 3: Manually smoke-test the UI**

Run: `.\.venv\Scripts\python.exe -m src.app`
In the app window: open Integrations → confirm the "Brokerage (Robinhood)" section renders with the explainer, the collapsible how-to, two key fields, and the three buttons. Paste your real keys → Save keys (status: "Keys saved ✓") → Connect Robinhood (a SnapTrade tab opens) → after authorizing, status flips to "Connected ✓ — N account(s)." Close the app window when done.

- [ ] **Step 4: Add a static-UI assertion test**

Add to `tests/test_ui_static.py` (follow the file's existing style of reading `ui/` files; if it reads files via a helper, reuse it — otherwise read with `pathlib`):

```python
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


def test_integrations_html_has_brokerage_controls():
    html = (UI / "index.html").read_text(encoding="utf-8")
    for el in ("snap-client-id", "snap-consumer-key", "connect-broker-btn",
               "check-broker-btn", "disconnect-broker-btn"):
        assert el in html


def test_app_js_wires_brokerage_endpoints():
    js = (UI / "app.js").read_text(encoding="utf-8")
    assert "/api/integrations/brokerage/keys" in js
    assert "/api/integrations/brokerage/connect" in js
    assert "/api/integrations/brokerage/verify" in js
    assert "/api/integrations/brokerage/disconnect" in js
```

- [ ] **Step 5: Run the UI test to verify it passes**

Run: `pytest tests/test_ui_static.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ui/index.html ui/app.js tests/test_ui_static.py
git commit -m "feat: Connect Robinhood UI in the Integrations tab"
```

---

### Task 6: Full suite + final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `pytest -q`
Expected: PASS, with the new tests included and no regressions. If anything fails, fix it before proceeding (do not claim completion on red).

- [ ] **Step 2: Confirm the owner's repo profile is unaffected**

Run: `pytest tests/test_profile.py tests/test_profile_keyring.py -v`
Expected: PASS — `Profile.for_repo` still keyring-disabled; owner `.env` behavior unchanged.

- [ ] **Step 3: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "test: full suite green for Connect Robinhood button"
```

(Skip if Step 1 was already green and nothing changed.)

---

## Self-Review Notes

- **Spec coverage:** seam module (Task 2) ✓; BYO keys + guardrail copy (Task 5) ✓; keyring secrets + integrations.yaml identifiers (Task 1) ✓; routes incl. write-only secrets (Task 3) ✓; connect data flow incl. auto-poll (Task 5) ✓; error handling 400/502 + yaml fallback already in `main.run` ✓; testing via fakes + temp profile ✓; deprecation fix (Task 4) ✓; non-goals (no cloud backend, owner profile untouched) — Task 6 Step 2 guards the latter.
- **Type/name consistency:** `brokerage_link` surface — `save_keys`, `start_connect`, `check_connection`, `disconnect`, `keys_present`, `is_linked`, `BrokerageError` — used identically across Tasks 2/3. `check_connection` returns `{connected, account_count}` everywhere. Config helpers `save_brokerage_identity` / `load_integrations` keys (`SNAPTRADE_CLIENT_ID`, `SNAPTRADE_USER_ID`) consistent across Tasks 1/2/3.
- **SaaS seam:** routes/UI depend only on the six `brokerage_link` names; swapping the four lifecycle functions to a hosted implementation requires no route/UI change.
```
