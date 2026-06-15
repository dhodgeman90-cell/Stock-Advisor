from pathlib import Path
from src.profile import EnvSecrets


def test_envsecrets_reads_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text(
        '# comment\nANTHROPIC_API_KEY=sk-abc\nEMAIL_USER="me@x.com"\n\n',
        encoding="utf-8",
    )
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("ANTHROPIC_API_KEY") == "sk-abc"
    assert s.get("EMAIL_USER") == "me@x.com"          # surrounding quotes stripped
    assert s.get("MISSING") is None
    assert s.get("MISSING", "fallback") == "fallback"


def test_envsecrets_missing_file_is_empty(tmp_path):
    s = EnvSecrets(dotenv_path=tmp_path / "nope.env")
    assert s.get("ANYTHING") is None


def test_envsecrets_file_value_beats_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FOO", "from-env")
    (tmp_path / ".env").write_text("FOO=from-file\n", encoding="utf-8")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("FOO") == "from-file"


def test_envsecrets_falls_back_to_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BAR", "from-env")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")   # no file
    assert s.get("BAR") == "from-env"


def test_envsecrets_explicit_values_dict(tmp_path):
    s = EnvSecrets(values={"K": "v"})
    assert s.get("K") == "v"


def test_apply_to_environ_does_not_clobber_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEP", "already")
    s = EnvSecrets(values={"KEEP": "new", "ADD": "added"})
    s.apply_to_environ()
    import os
    assert os.environ["KEEP"] == "already"   # setdefault semantics, matches load_dotenv
    assert os.environ["ADD"] == "added"


from src.profile import Profile, ROOT


def test_profile_for_repo_uses_repo_dirs():
    p = Profile.for_repo()
    assert p.config_dir == ROOT / "config"
    assert p.data_dir == ROOT / "data"
    assert p.reports_dir == ROOT / "reports"
    assert p.secrets.get("definitely-not-a-real-key") is None


def test_profile_for_base_roots_all_dirs(tmp_path):
    p = Profile.for_base(tmp_path)
    assert p.config_dir == tmp_path / "config"
    assert p.data_dir == tmp_path / "data"
    assert p.reports_dir == tmp_path / "reports"


def test_profile_ensure_dirs_creates_them(tmp_path):
    p = Profile.for_base(tmp_path / "app")
    assert not p.config_dir.exists()
    p.ensure_dirs()
    assert p.config_dir.is_dir()
    assert p.data_dir.is_dir()
    assert p.reports_dir.is_dir()


# ---- robust .env parsing (delegates to python-dotenv, already a dependency) ----

def test_envsecrets_strips_inline_comment(tmp_path):
    # A commented value must not leak the comment into the value — otherwise
    # int(EMAIL_PORT) downstream would crash on "465  # gmail SSL".
    (tmp_path / ".env").write_text("EMAIL_PORT=465  # gmail SSL\n", encoding="utf-8")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("EMAIL_PORT") == "465"


def test_envsecrets_handles_export_prefix(tmp_path):
    (tmp_path / ".env").write_text("export FOO=bar\n", encoding="utf-8")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("FOO") == "bar"


def test_envsecrets_preserves_literal_dollar_sign(tmp_path):
    # Secrets are opaque: a literal $ must never be expanded as a ${VAR} reference.
    (tmp_path / ".env").write_text("SECRET=ab$cd\n", encoding="utf-8")
    s = EnvSecrets(dotenv_path=tmp_path / ".env")
    assert s.get("SECRET") == "ab$cd"
