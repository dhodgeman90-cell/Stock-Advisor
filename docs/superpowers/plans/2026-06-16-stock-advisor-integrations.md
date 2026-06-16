# Stock Advisor Integrations (BYO AI key + email) — Implementation Plan (Plan 2b of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the static "coming soon" Integrations panel into a working settings page where a tinkerer can (a) bring their own Anthropic API key to enable the AI agents and (b) bring their own Gmail app password to have the briefing emailed — with the two true secrets stored in the **OS credential store** (never plaintext, never read back), the non-secret email routing fields in a per-user config file, and the engine consuming all of it **unchanged** through `profile.secrets.get(KEY)`.

**Architecture:** Add a tiny `secrets_store` module wrapping the `keyring` library (on Windows this is the Credential Manager, DPAPI-backed). The two secret keys (`ANTHROPIC_API_KEY`, `EMAIL_PASSWORD`) live there; the four non-secret email fields (`EMAIL_USER`, `EMAIL_TO`, `EMAIL_HOST`, `EMAIL_PORT`) live in `config/integrations.yaml`. The existing `EnvSecrets` read-interface gains two new layers so its precedence becomes **OS credential store → integrations.yaml → profile `.env` → process env** — but *only for the per-user app profile* (`Profile.for_base`); the owner's repo CLI (`Profile.for_repo`) stays `.env`-only and completely unchanged. A new `routes_integrations` module exposes write-only/status-only endpoints, and the UI Integrations screen becomes two small forms.

**Tech Stack:** Python 3, `keyring` (new dep — OS credential store), FastAPI + Pydantic v2 (routes), pytest with an autouse fixture that swaps `keyring` for an in-memory fake so **no test ever touches the real OS credential store**, plain HTML/JS (UI). Reuses the existing `briefing.send_email` (already injectable for tests).

**Part of:** `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md` (Sections 5 & 9, "Optional add-ons → Integrations page: BYO AI key, BYO email"; Section 11 open item "OS credential-store mechanism (Windows DPAPI via keyring) and key names"). Builds on Plan 2 (`2026-06-15-stock-advisor-local-web-app.md`, merged to `main`), which shipped Integrations as a static placeholder. Plan 3 (packaging) builds on this — `keyring` must be bundled by PyInstaller (a `--hidden-import` note is left for Plan 3, no code here).

**Where this runs:** the Stock Advisor repo at `C:\VS Code\Stock Advisor` (not the Website Fuckery workspace). Do the work on a feature branch (e.g. `integrations`), mirroring how Plans 1 & 2 were branched then fast-forward merged. Activate the venv once per session, then run all commands from the repo root:

```powershell
& .\.venv\Scripts\Activate.ps1
```

After activation `pytest` and `python` resolve to the venv. (If you prefer not to activate: prefix commands with `& .\.venv\Scripts\python.exe -m`.)

---

## Decisions locked in (do not re-derive)

| Question (spec §11 open item) | Decision |
|---|---|
| Credential-store mechanism | `keyring` library. On Windows it uses the Credential Manager (DPAPI-backed) with **no extra install**. Cross-platform by default (macOS Keychain, Secret Service on Linux). |
| Service name / key names | Service constant `"StockAdvisor"`. Keys are the existing env var names: `ANTHROPIC_API_KEY`, `EMAIL_PASSWORD`. |
| Which fields are secret | **Secret (keyring, write-only, status only):** `ANTHROPIC_API_KEY`, `EMAIL_PASSWORD`. **Non-secret (config/integrations.yaml, readable/editable):** `EMAIL_USER`, `EMAIL_TO`, `EMAIL_HOST`, `EMAIL_PORT`. The big-dogs split: secrets in the credential store, routing config in a config file. |
| Read precedence (per-user app) | OS credential store → `integrations.yaml` → profile `.env` → process env. |
| Owner's repo CLI | **Unchanged.** `Profile.for_repo` keeps `keyring_service=None`, so it never consults the credential store or `integrations.yaml` — exactly today's `.env`-only behavior. Only `Profile.for_base` (the packaged per-user app) enables the new layers. |
| Test isolation | An **autouse** conftest fixture swaps `secrets_store`'s backend for an in-memory fake every test. No test reads or writes the real OS credential store. |

### Why the engine needs zero changes
`main.run()` already reads every secret through `secrets.get(KEY)` and pushes file values into `os.environ` via `secrets.apply_to_environ()` (so `anthropic.Anthropic()` and SMTP see them). We extend *those two methods* to also consult keyring + integrations config. `main.py` itself is untouched.

---

## File Structure

New modules (in `src/`):
- **`src/secrets_store.py`** — thin wrapper over `keyring`: `get_secret/set_secret/delete_secret/has_secret`, the `SERVICE` and `SECRET_KEYS` constants, and an injectable module-level backend (`set_backend`) so tests use an in-memory fake. One responsibility: *talk to the OS credential store.*
- **`src/routes_integrations.py`** — `GET /api/integrations` (status), `PUT /api/integrations/ai` (set/clear key), `PUT /api/integrations/email` (save config + optional password), `POST /api/integrations/email/test` (send a test email). One responsibility: *the Integrations HTTP surface.*

Modified:
- **`src/profile.py`** — `EnvSecrets` gains `keyring_service` + `config_values` layers in `get()` / `apply_to_environ()`, plus `update_config_values()`; `Profile.for_base` loads `integrations.yaml` and wires the keyring service. `Profile.for_repo` unchanged.
- **`src/config.py`** — add `load_integrations()` / `save_integrations()` (+ `INTEGRATION_FIELDS`).
- **`src/server.py`** — register `routes_integrations`.
- **`conftest.py`** — add the autouse keyring-isolation fixture.
- **`tests/fakes.py`** — add `FakeKeyring`.
- **`ui/index.html`** — replace the placeholder Integrations section with two forms.
- **`ui/app.js`** — load/save Integrations.
- **`ui/style.css`** — a couple of small helpers (only if needed; reuse existing classes).
- **`requirements.txt`** — add `keyring`.
- **`README.md`** — short "Integrations (optional)" note.

New tests (in `tests/`):
- `test_secrets_store.py`, `test_config_integrations.py`, `test_profile_keyring.py`, `test_server_integrations.py`.

Design facts locked in by reading the code (do not re-derive):
- `EnvSecrets.get(key, default)` today: profile `.env` dict → `os.environ`. `apply_to_environ()` does `os.environ.setdefault` for each `.env` value. (`src/profile.py`)
- `Profile.for_base(base)` builds `EnvSecrets(dotenv_path=base/".env")`; `Profile.for_repo()` builds `EnvSecrets(dotenv_path=ROOT/".env")`. Both are frozen dataclasses, but the `EnvSecrets` instance they hold is mutable. (`src/profile.py`)
- `main.run()` calls `secrets = profile.secrets; secrets.apply_to_environ()` then reads `secrets.get("ANTHROPIC_API_KEY")` and `secrets.get("EMAIL_USER"/"EMAIL_PASSWORD"/"EMAIL_TO"/"EMAIL_HOST"/"EMAIL_PORT")`. (`src/main.py:103-104, 215, 297-305`)
- `briefing.send_email(subject, body, *, host, port, user, password, to_addr, html_body=None, smtp_factory=None)` — `smtp_factory` is injectable for tests. (`src/briefing.py:377`)
- Route modules expose `def register(app)` and are registered in `server.create_app`. Routes get the profile via `Depends(get_profile)`. Pydantic `BaseModel` bodies validate input. (`src/routes_settings.py`, `src/server.py`)
- `config._atomic_write_yaml(path, data)` exists; loaders that tolerate a missing file return `{}` (see `load_signals`, `load_position_overrides`). (`src/config.py`)
- Server tests build `TestClient(server.create_app(Profile.for_base(tmp_path)))` after `onboarding.seed_profile(profile)`. (`tests/test_server_settings.py`)
- The repo-root `conftest.py` is currently effectively empty; tests import `from src.x import y` and `from tests.fakes import ...`. (`conftest.py`, `tests/fakes.py`)

---

## Task 1: `secrets_store` — keyring wrapper + test isolation

**Files:**
- Create: `src/secrets_store.py`
- Modify: `tests/fakes.py`
- Modify: `conftest.py`
- Test: `tests/test_secrets_store.py`

- [ ] **Step 1: Add `FakeKeyring` to `tests/fakes.py`**

Append to `tests/fakes.py`:

```python
class FakeKeyring:
    """In-memory stand-in for the `keyring` module's password API.

    Used by the autouse conftest fixture so tests never touch the real OS
    credential store. Mirrors keyring's interface: set/get/delete_password,
    keyed by (service, key). delete of a missing key raises, like keyring does.
    """

    def __init__(self):
        self._store = {}

    def get_password(self, service, key):
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self._store[(service, key)] = value

    def delete_password(self, service, key):
        if (service, key) not in self._store:
            raise KeyError(f"no such password: {service}/{key}")
        del self._store[(service, key)]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_secrets_store.py`:

```python
from src import secrets_store


def test_set_get_has_and_delete():
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-abc")
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") == "sk-abc"
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is True
    secrets_store.delete_secret("ANTHROPIC_API_KEY")
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") is None
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False


def test_delete_missing_is_a_noop():
    # Must not raise even though the underlying keyring delete raises.
    secrets_store.delete_secret("EMAIL_PASSWORD")


def test_get_missing_is_none():
    assert secrets_store.get_secret("EMAIL_PASSWORD") is None


def test_backend_failure_degrades_to_none(monkeypatch):
    class Boom:
        def get_password(self, *a):
            raise RuntimeError("no backend")

    secrets_store.set_backend(Boom())
    # A broken/absent credential backend must not crash a run.
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") is None
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False


def test_expected_constants():
    assert secrets_store.SERVICE == "StockAdvisor"
    assert set(secrets_store.SECRET_KEYS) == {"ANTHROPIC_API_KEY", "EMAIL_PASSWORD"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_secrets_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.secrets_store'`.

(The autouse fixture from Step 5 supplies the fake backend; until Step 4 + Step 5 exist these fail to import.)

- [ ] **Step 4: Implement `src/secrets_store.py`**

Create `src/secrets_store.py`:

```python
"""Thin wrapper over the OS credential store (via the `keyring` library).

On Windows this is the Credential Manager (DPAPI-backed) — no extra install.
The per-user app stores exactly two secrets here (SECRET_KEYS); everything else
is non-secret config. The backend is swappable (set_backend) so tests use an
in-memory fake and never touch the real credential store. All reads degrade to
None if no backend is available, so a missing credential store never crashes a run.
"""
from __future__ import annotations

SERVICE = "StockAdvisor"
SECRET_KEYS = ("ANTHROPIC_API_KEY", "EMAIL_PASSWORD")

_backend = None


def set_backend(backend) -> None:
    """Override the keyring backend (tests inject an in-memory fake)."""
    global _backend
    _backend = backend


def _get_backend():
    global _backend
    if _backend is None:
        import keyring
        _backend = keyring
    return _backend


def get_secret(key: str):
    try:
        return _get_backend().get_password(SERVICE, key) or None
    except Exception:
        return None


def set_secret(key: str, value: str) -> None:
    _get_backend().set_password(SERVICE, key, value)


def delete_secret(key: str) -> None:
    try:
        _get_backend().delete_password(SERVICE, key)
    except Exception:
        pass   # deleting an unset secret is a no-op


def has_secret(key: str) -> bool:
    return get_secret(key) is not None
```

- [ ] **Step 5: Add the autouse isolation fixture to `conftest.py`**

The repo-root `conftest.py` is currently effectively empty. Set its full contents to:

```python
import pytest

from src import secrets_store
from tests.fakes import FakeKeyring


@pytest.fixture(autouse=True)
def _isolate_keyring():
    """Every test gets a fresh in-memory credential store. No test ever reads or
    writes the real OS credential store."""
    secrets_store.set_backend(FakeKeyring())
    yield
    secrets_store.set_backend(None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_secrets_store.py -v`
Expected: PASS (all 5).

- [ ] **Step 7: Run the full suite to confirm the autouse fixture broke nothing**

Run: `pytest -q`
Expected: PASS — same count as before plus the 5 new tests. (The autouse fixture is inert for tests that never call `secrets_store`.)

- [ ] **Step 8: Commit**

```bash
git add src/secrets_store.py tests/test_secrets_store.py tests/fakes.py conftest.py
git commit -m "feat: secrets_store keyring wrapper + test isolation fixture"
```

---

## Task 2: `config.load_integrations` / `save_integrations`

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config_integrations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_integrations.py`:

```python
from src import config


def test_load_missing_file_is_empty(tmp_path):
    assert config.load_integrations(tmp_path) == {}


def test_save_then_load_roundtrip(tmp_path):
    config.save_integrations(tmp_path, user="me@gmail.com", to="me@gmail.com",
                             host="smtp.gmail.com", port="465")
    loaded = config.load_integrations(tmp_path)
    assert loaded == {
        "EMAIL_USER": "me@gmail.com",
        "EMAIL_TO": "me@gmail.com",
        "EMAIL_HOST": "smtp.gmail.com",
        "EMAIL_PORT": "465",
    }


def test_blank_fields_are_omitted_not_stored_as_empty(tmp_path):
    # Saving with blanks must not write empty strings the engine would treat as "set".
    config.save_integrations(tmp_path, user="me@gmail.com", to="", host="", port="")
    assert config.load_integrations(tmp_path) == {"EMAIL_USER": "me@gmail.com"}


def test_values_are_stringified_and_trimmed(tmp_path):
    config.save_integrations(tmp_path, user="  me@gmail.com  ", to="you@x.com",
                             host="smtp.gmail.com", port=587)
    loaded = config.load_integrations(tmp_path)
    assert loaded["EMAIL_USER"] == "me@gmail.com"
    assert loaded["EMAIL_PORT"] == "587"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_config_integrations.py -v`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'load_integrations'`.

- [ ] **Step 3: Implement the loader/saver in `src/config.py`**

Append to `src/config.py` (after `save_positions`):

```python
INTEGRATION_FIELDS = ("EMAIL_USER", "EMAIL_TO", "EMAIL_HOST", "EMAIL_PORT")


def load_integrations(config_dir) -> dict:
    """Non-secret email routing config from integrations.yaml, keyed by env-var name.

    Secrets (the Anthropic key, the email app password) are NOT here — those live in
    the OS credential store (see src/secrets_store.py). A missing/blank file yields {}.
    """
    path = Path(config_dir) / "integrations.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    email = data.get("email") or {}
    out = {}
    for env_key, yaml_key in (("EMAIL_USER", "user"), ("EMAIL_TO", "to"),
                              ("EMAIL_HOST", "host"), ("EMAIL_PORT", "port")):
        val = email.get(yaml_key)
        if val is not None and str(val).strip() != "":
            out[env_key] = str(val).strip()
    return out


def save_integrations(config_dir, *, user="", to="", host="", port="") -> None:
    """Persist non-secret email config to integrations.yaml. Blank fields are omitted
    (never written as empty strings, which the engine would misread as 'configured')."""
    email = {}
    for yaml_key, val in (("user", user), ("to", to), ("host", host), ("port", port)):
        if val is not None and str(val).strip() != "":
            email[yaml_key] = str(val).strip()
    _atomic_write_yaml(Path(config_dir) / "integrations.yaml", {"email": email})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_config_integrations.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_integrations.py
git commit -m "feat: load/save non-secret email config in integrations.yaml"
```

---

## Task 3: Layer keyring + integrations config into `EnvSecrets` / `Profile`

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile_keyring.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_keyring.py`:

```python
import os

from src import secrets_store, config
from src.profile import EnvSecrets, Profile


def test_get_prefers_keyring_then_config_then_env(tmp_path, monkeypatch):
    # .env on disk holds an old value; keyring holds the live one and must win.
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n", encoding="utf-8")
    secrets_store.set_secret("ANTHROPIC_API_KEY", "from-keyring")
    s = EnvSecrets(dotenv_path=tmp_path / ".env",
                   keyring_service=secrets_store.SERVICE,
                   config_values={"EMAIL_USER": "me@x.com"})
    assert s.get("ANTHROPIC_API_KEY") == "from-keyring"     # keyring beats .env
    assert s.get("EMAIL_USER") == "me@x.com"                # config layer
    monkeypatch.setenv("EMAIL_TO", "amb@x.com")
    assert s.get("EMAIL_TO") == "amb@x.com"                 # falls through to env


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_profile_keyring.py -v`
Expected: FAIL — `EnvSecrets.__init__() got an unexpected keyword argument 'keyring_service'`.

- [ ] **Step 3: Extend `EnvSecrets` in `src/profile.py`**

Replace the `EnvSecrets.__init__`, `get`, and `apply_to_environ` (and add `update_config_values`) so the class reads:

```python
class EnvSecrets:
    """Secret/config lookup with a fixed precedence. For the per-user app the order is
    OS credential store -> integrations.yaml config -> profile .env -> process env. For
    the owner's repo profile, keyring_service is None and config_values is empty, so it
    degrades to the original .env -> process-env behavior (owner CLI unchanged).

    apply_to_environ() pushes the resolved values into os.environ (without clobbering
    existing vars) for the downstream modules (broker, llm, congress) that read
    os.environ directly.
    """

    def __init__(self, dotenv_path: Optional[Path] = None, values: Optional[dict] = None,
                 *, keyring_service: Optional[str] = None, config_values: Optional[dict] = None):
        self._dotenv_path = Path(dotenv_path) if dotenv_path else None
        if values is not None:
            self._values = dict(values)
        else:
            self._values = self._read_dotenv(self._dotenv_path)
        self._keyring_service = keyring_service
        self._config_values = dict(config_values or {})

    @staticmethod
    def _read_dotenv(path: Optional[Path]) -> dict:
        if not path or not path.exists():
            return {}
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(path, interpolate=False, encoding="utf-8").items()
                if v is not None}

    def update_config_values(self, mapping: dict) -> None:
        """Replace the in-memory non-secret config layer (after the user edits it via
        the API), so the change takes effect without restarting the server."""
        self._config_values = dict(mapping or {})

    def get(self, key: str, default=None):
        if self._keyring_service is not None:
            from src import secrets_store
            if key in secrets_store.SECRET_KEYS:
                kv = secrets_store.get_secret(key)
                if kv:
                    return kv
        cv = self._config_values.get(key)
        if cv is not None and cv != "":
            return cv
        val = self._values.get(key)
        if val is not None and val != "":
            return val
        return os.environ.get(key, default)

    def apply_to_environ(self) -> None:
        if self._keyring_service is not None:
            from src import secrets_store
            for k in secrets_store.SECRET_KEYS:
                kv = secrets_store.get_secret(k)
                if kv:
                    os.environ.setdefault(k, kv)
        for key, val in self._config_values.items():
            if val not in (None, ""):
                os.environ.setdefault(key, str(val))
        for key, val in self._values.items():
            if val != "":
                os.environ.setdefault(key, val)
```

Note: the `from __future__ import annotations`, `import os`, and `from typing import Optional` at the top of `profile.py` already exist — keep them.

- [ ] **Step 4: Wire `Profile.for_base` to load integrations + enable keyring**

In `src/profile.py`, replace `Profile.for_base` with:

```python
    @classmethod
    def for_base(cls, base) -> "Profile":
        """Per-user profile rooted at an arbitrary base dir (e.g. %APPDATA%/StockAdvisor).

        Enables the OS credential store (for the two secret keys) and loads the
        non-secret email config from integrations.yaml. The owner's repo profile
        (for_repo) deliberately does NOT enable these."""
        from src import config as _config
        from src import secrets_store
        base = Path(base)
        config_dir = base / "config"
        return cls(
            config_dir=config_dir,
            data_dir=base / "data",
            reports_dir=base / "reports",
            secrets=EnvSecrets(
                dotenv_path=base / ".env",
                keyring_service=secrets_store.SERVICE,
                config_values=_config.load_integrations(config_dir),
            ),
        )
```

Leave `Profile.for_repo` exactly as it is (no `keyring_service`, no `config_values`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_profile_keyring.py tests/test_profile.py -v`
Expected: PASS — the new keyring tests pass and the **existing** `test_profile.py` tests still pass (the new params default to off).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS. (Server tests that build `Profile.for_base(tmp_path)` now also exercise the keyring layer via the fake backend, with `integrations.yaml` absent → `{}`.)

- [ ] **Step 7: Commit**

```bash
git add src/profile.py tests/test_profile_keyring.py
git commit -m "feat: layer OS credential store + integrations config into EnvSecrets/Profile.for_base"
```

---

## Task 4: `routes_integrations` — status / write-only secrets / test email

**Files:**
- Create: `src/routes_integrations.py`
- Modify: `src/server.py`
- Test: `tests/test_server_integrations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_integrations.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_server_integrations.py -v`
Expected: FAIL — `404` on every route (routes not registered yet) / `ModuleNotFoundError: src.routes_integrations`.

- [ ] **Step 3: Implement `src/routes_integrations.py`**

Create `src/routes_integrations.py`:

```python
"""Integrations: bring-your-own Anthropic key (AI) and Gmail app password (email).

Secrets (the Anthropic key, the email app password) are write-only: they go to the
OS credential store and are NEVER returned in plaintext — the status endpoint reports
only set/not-set. Non-secret email routing fields live in integrations.yaml and ARE
returned so the user can see and edit them.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config, secrets_store, briefing
from src.deps import get_profile


class AiBody(BaseModel):
    api_key: str = ""           # "" clears the stored key


class EmailBody(BaseModel):
    user: str = ""
    to: str = ""
    host: str = "smtp.gmail.com"
    port: str = "465"
    password: Optional[str] = None   # None = leave existing; "" = clear; value = set


def register(app) -> None:
    @app.get("/api/integrations")
    def get_integrations(profile=Depends(get_profile)):
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
        }

    @app.put("/api/integrations/ai")
    def put_ai(body: AiBody):
        key = (body.api_key or "").strip()
        if key:
            secrets_store.set_secret("ANTHROPIC_API_KEY", key)
        else:
            secrets_store.delete_secret("ANTHROPIC_API_KEY")
        return {"ok": True, "key_set": secrets_store.has_secret("ANTHROPIC_API_KEY")}

    @app.put("/api/integrations/email")
    def put_email(body: EmailBody, profile=Depends(get_profile)):
        config.save_integrations(profile.config_dir, user=body.user, to=body.to,
                                 host=body.host, port=body.port)
        # Refresh the live profile so a run/test in this session uses the new config.
        profile.secrets.update_config_values(config.load_integrations(profile.config_dir))
        if body.password is not None:
            pw = body.password.strip()
            if pw:
                secrets_store.set_secret("EMAIL_PASSWORD", pw)
            else:
                secrets_store.delete_secret("EMAIL_PASSWORD")
        return {"ok": True, "password_set": secrets_store.has_secret("EMAIL_PASSWORD")}

    @app.post("/api/integrations/email/test")
    def test_email(profile=Depends(get_profile)):
        s = profile.secrets
        missing = [k for k in ("EMAIL_USER", "EMAIL_TO") if not s.get(k)]
        if not secrets_store.has_secret("EMAIL_PASSWORD"):
            missing.append("EMAIL_PASSWORD")
        if missing:
            raise HTTPException(status_code=400,
                                detail=f"Email not fully configured: missing {', '.join(missing)}")
        try:
            briefing.send_email(
                "Stock Advisor — test email",
                "This is a test email from Stock Advisor. Your email integration works.",
                host=s.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(s.get("EMAIL_PORT", "465")),
                user=s.get("EMAIL_USER"),
                password=s.get("EMAIL_PASSWORD"),
                to_addr=s.get("EMAIL_TO"),
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Send failed: {e}") from e
        return {"ok": True}
```

- [ ] **Step 4: Register the routes in `src/server.py`**

In `src/server.py`, after the `routes_briefing` registration block, add:

```python
    from src import routes_integrations
    routes_integrations.register(app)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_server_integrations.py -v`
Expected: PASS (all 8).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/routes_integrations.py src/server.py tests/test_server_integrations.py
git commit -m "feat: /api/integrations status, write-only secrets, test-email route"
```

---

## Task 5: Integrations UI (forms + wiring)

**Files:**
- Modify: `ui/index.html`
- Modify: `ui/app.js`
- Modify: `ui/style.css` (only if a needed class is missing)
- Test: `tests/test_ui_static.py` (extend the existing smoke test)

- [ ] **Step 1: Write the failing UI smoke assertions**

Open `tests/test_ui_static.py` and look at the existing test that fetches `/app.js` and `/` (it asserts substrings exist). Add a new test mirroring its style:

```python
def test_integrations_ui_is_wired(tmp_path):
    client = _client(tmp_path)   # reuse the helper already in this file
    html = client.get("/").text
    assert 'id="ai-key"' in html
    assert 'id="email-user"' in html
    assert 'id="test-email-btn"' in html
    js = client.get("/app.js").text
    assert "/api/integrations" in js
    assert "loadIntegrations" in js
```

If `test_ui_static.py` has no `_client` helper, add the same one used elsewhere:

```python
from fastapi.testclient import TestClient
from src import server, onboarding
from src.profile import Profile

def _client(tmp_path):
    profile = Profile.for_base(tmp_path)
    onboarding.seed_profile(profile)
    return TestClient(server.create_app(profile))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_static.py::test_integrations_ui_is_wired -v`
Expected: FAIL — `'id="ai-key"' in html` is False (placeholder markup still there).

- [ ] **Step 3: Replace the Integrations section in `ui/index.html`**

Replace the entire `<section id="screen-integrations" ...>...</section>` block with:

```html
  <section id="screen-integrations" class="screen hidden">
    <h1>Integrations</h1>
    <p class="muted">All optional. The app runs fully on rules-based signals without any of these.
    Keys are stored in your computer's credential manager and never shown again.</p>

    <h2>AI analysis</h2>
    <p class="muted">Bring your own Anthropic API key to enable the AI agents on actionable days.</p>
    <div class="field"><label>Anthropic API key
      <input id="ai-key" type="password" placeholder="sk-ant-…" autocomplete="off"></label></div>
    <span id="ai-status" class="muted"></span>
    <div class="row">
      <button id="save-ai-btn">Save key</button>
      <button id="clear-ai-btn">Clear</button>
    </div>

    <h2>Email briefing</h2>
    <p class="muted">Bring your own Gmail <b>app password</b> (not your normal password) to have the
    briefing emailed to you.</p>
    <div class="field"><label>From address (Gmail)
      <input id="email-user" type="email" placeholder="you@gmail.com" autocomplete="off"></label></div>
    <div class="field"><label>Send to
      <input id="email-to" type="email" placeholder="you@gmail.com" autocomplete="off"></label></div>
    <div class="field"><label>SMTP host
      <input id="email-host" type="text" value="smtp.gmail.com"></label></div>
    <div class="field"><label>SMTP port
      <input id="email-port" type="text" value="465"></label></div>
    <div class="field"><label>App password
      <input id="email-pass" type="password" placeholder="leave blank to keep current" autocomplete="off"></label></div>
    <span id="email-status" class="muted"></span>
    <div class="row">
      <button id="save-email-btn">Save email settings</button>
      <button id="test-email-btn">Send test email</button>
    </div>
    <span id="integrations-msg" class="msg"></span>
  </section>
```

- [ ] **Step 4: Add the Integrations logic to `ui/app.js`**

In `ui/app.js`, in `showScreen()` add an integrations branch next to the existing ones:

```javascript
  if (name === "integrations") loadIntegrations();
```

Then add this block (e.g. after the positions section, before `// ---- boot ----`):

```javascript
// ---- integrations ----
async function loadIntegrations() {
  const d = await api("/api/integrations");
  $("#ai-status").textContent = d.ai.key_set ? "Key saved ✓" : "No key set.";
  $("#ai-key").value = "";
  $("#email-user").value = d.email.user || "";
  $("#email-to").value = d.email.to || "";
  $("#email-host").value = d.email.host || "smtp.gmail.com";
  $("#email-port").value = d.email.port || "465";
  $("#email-pass").value = "";
  $("#email-status").textContent = d.email.password_set ? "App password saved ✓" : "No app password set.";
  $("#integrations-msg").textContent = "";
}
$("#save-ai-btn").addEventListener("click", async () => {
  try {
    await api("/api/integrations/ai", { method: "PUT",
      body: JSON.stringify({ api_key: $("#ai-key").value.trim() }) });
    $("#integrations-msg").textContent = "AI key saved.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Save failed: " + e.message; }
});
$("#clear-ai-btn").addEventListener("click", async () => {
  try {
    await api("/api/integrations/ai", { method: "PUT", body: JSON.stringify({ api_key: "" }) });
    $("#integrations-msg").textContent = "AI key cleared.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Clear failed: " + e.message; }
});
$("#save-email-btn").addEventListener("click", async () => {
  const body = {
    user: $("#email-user").value.trim(),
    to: $("#email-to").value.trim(),
    host: $("#email-host").value.trim() || "smtp.gmail.com",
    port: $("#email-port").value.trim() || "465",
  };
  const pw = $("#email-pass").value;          // omit when blank -> keep existing
  if (pw) body.password = pw;
  try {
    await api("/api/integrations/email", { method: "PUT", body: JSON.stringify(body) });
    $("#integrations-msg").textContent = "Email settings saved.";
    loadIntegrations();
  } catch (e) { $("#integrations-msg").textContent = "Save failed: " + e.message; }
});
$("#test-email-btn").addEventListener("click", async () => {
  $("#integrations-msg").textContent = "Sending test email…";
  try {
    await api("/api/integrations/email/test", { method: "POST" });
    $("#integrations-msg").textContent = "Test email sent — check your inbox.";
  } catch (e) { $("#integrations-msg").textContent = "Test failed: " + e.message; }
});
```

Note: the shared `api()` helper throws on non-2xx with a message like `"/api/integrations/email/test -> 400"`. That is acceptable for the beta (the detail text is in the server log); a nicer error surfacing is a later polish, not MVP.

- [ ] **Step 5: `ui/style.css` — only if needed**

The new markup reuses existing classes (`field`, `row`, `muted`, `msg`, `screen`). If `<h2>` inside a screen looks unstyled, add a minimal rule; otherwise skip this step. Do not restyle existing screens.

- [ ] **Step 6: Run the UI test to verify it passes**

Run: `pytest tests/test_ui_static.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/index.html ui/app.js ui/style.css tests/test_ui_static.py
git commit -m "feat: Integrations UI — BYO AI key + email forms with test-send"
```

---

## Task 6: Dependency, docs, and manual verification

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Add `keyring` to `requirements.txt`**

Add this line (group it near the other runtime deps):

```
keyring>=24          # OS credential store for BYO AI key + email app password (Integrations)
```

- [ ] **Step 2: Install it into the venv**

Run: `python -m pip install "keyring>=24"`
Expected: installs `keyring` (and its small dependency tree, e.g. `pywin32-ctypes`/`jaraco.*` on Windows).

- [ ] **Step 3: Add a README note**

In `README.md`, under the "Run the local app" section, add:

```markdown
### Integrations (optional)

The app runs fully on rules-based signals with no setup. Two optional power features
live on the **Integrations** screen:

- **AI analysis** — paste your own Anthropic API key to enable the AI agents on
  actionable days.
- **Email briefing** — enter a Gmail address and a Gmail **app password** (not your
  normal password) to have the briefing emailed. Use **Send test email** to confirm it.

Keys are stored in your operating system's credential manager (Windows Credential
Manager / macOS Keychain) — never in a plaintext file, and never shown again after you
save them.
```

- [ ] **Step 4: Full suite must pass**

Run: `pytest -q`
Expected: PASS — all prior tests plus the new ones.

- [ ] **Step 5: Manual end-to-end check (owner-run, explained for a beginner)**

This step proves the real OS credential store path works (tests use the fake). Run the app:

```powershell
python -m src.app
```

What this does: starts the local server on `127.0.0.1` and opens your browser. Then, **by hand**:
1. Go to **Integrations**. Confirm both show "not set".
2. Paste a throwaway/real Anthropic key → **Save key** → it flips to "Key saved ✓". Reload the page; it still says saved but the field is blank (never echoed).
3. Open **Windows Credential Manager → Windows Credentials** and confirm an entry for `StockAdvisor` exists (proves DPAPI storage, not plaintext).
4. (Optional, if you have a Gmail app password) enter email settings + app password → **Save** → **Send test email** → check your inbox.
5. Click **Clear** on the AI key → it returns to "not set" and the Credential Manager entry is gone.

Stop the server with Ctrl+C.

> If anything here misbehaves, STOP and report it — do not paper over it. This is the one path tests can't cover (they mock the credential store by design).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt README.md
git commit -m "build: add keyring dep + document optional Integrations"
```

---

## Completion

After all tasks pass and the manual check is clean:
- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch — verify the full suite, then present merge/PR options (Plans 1 & 2 were fast-forward merged to `main`).
- Note for **Plan 3 (packaging):** PyInstaller must bundle `keyring`'s Windows backend — add `--hidden-import keyring.backends.Windows` (and `--collect-submodules keyring`) to the spec; no code change is needed here. The credential store is per-OS-user, so it works unchanged inside the packaged app.

---

## Self-Review (done while writing)

**Spec coverage:** Integrations page with BYO Anthropic key (Task 4/5) ✓; BYO Gmail email (Task 2/4/5) ✓; secrets in OS credential store, write-only/status-only (Task 1/3/4) ✓ (spec §5 `PUT /api/secrets` intent — implemented as the clearer `/api/integrations*` group, secrets never read back); key names + DPAPI mechanism resolved (spec §11) ✓; engine + owner CLI unchanged (Task 3, `for_repo` untouched) ✓; bundling note handed to Plan 3 ✓.

**Placeholder scan:** none — every code/test step contains complete code and exact commands.

**Type/name consistency:** `secrets_store.SERVICE` / `SECRET_KEYS` / `get_secret/set_secret/delete_secret/has_secret/set_backend` used identically across Tasks 1, 3, 4; `EnvSecrets(..., keyring_service=, config_values=)` + `update_config_values` consistent in Tasks 3, 4; `config.load_integrations/save_integrations` consistent in Tasks 2, 3, 4; route paths `/api/integrations`, `/api/integrations/ai`, `/api/integrations/email`, `/api/integrations/email/test` consistent across Tasks 4, 5; UI element ids (`ai-key`, `email-user`, `email-pass`, `test-email-btn`) consistent between Task 5 HTML and JS.
