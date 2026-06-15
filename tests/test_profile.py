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
