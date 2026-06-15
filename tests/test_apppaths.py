from pathlib import Path
from src.apppaths import user_base_dir


def test_override_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_ADVISOR_HOME", str(tmp_path / "custom"))
    assert user_base_dir() == tmp_path / "custom"


def test_appdata_used_when_no_override(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCK_ADVISOR_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert user_base_dir() == tmp_path / "Roaming" / "StockAdvisor"


def test_home_fallback_when_no_appdata(monkeypatch):
    monkeypatch.delenv("STOCK_ADVISOR_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert user_base_dir() == Path.home() / ".stockadvisor"
