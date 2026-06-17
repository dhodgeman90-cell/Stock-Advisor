from pathlib import Path

from scripts.verify_build import find_forbidden


def _touch(p: Path, text: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_clean_bundle_has_no_problems(tmp_path):
    # A legit one-folder build: exe + _internal with bundled defaults + ui.
    _touch(tmp_path / "StockAdvisor.exe")
    _touch(tmp_path / "_internal" / "defaults" / "watchlist.yaml", "tickers:\n  - AAPL\n")
    _touch(tmp_path / "_internal" / "defaults" / "positions.yaml", "positions: []\n")
    _touch(tmp_path / "_internal" / "ui" / "index.html", "<html></html>")
    _touch(tmp_path / "_internal" / "base_library.zip")
    assert find_forbidden(tmp_path) == []


def test_flags_bundled_dotenv(tmp_path):
    _touch(tmp_path / "_internal" / ".env", "ANTHROPIC_API_KEY=sk-real\n")
    problems = find_forbidden(tmp_path)
    assert any(".env" in p for p in problems)


def test_flags_secret_marker_in_any_text_file(tmp_path):
    # Even if a config is misnamed, a secret marker in its contents must be caught.
    _touch(tmp_path / "_internal" / "config" / "leak.yaml", "EMAIL_PASSWORD: hunter2\n")
    problems = find_forbidden(tmp_path)
    assert any("EMAIL_PASSWORD" in p for p in problems)


def test_flags_owner_email_marker(tmp_path):
    _touch(tmp_path / "_internal" / "notes.txt", "contact dhodgeman90@gmail.com")
    assert find_forbidden(tmp_path) != []


def test_flags_config_yaml_outside_defaults(tmp_path):
    # The owner's real configs must only ever ship as bundled defaults/.
    _touch(tmp_path / "_internal" / "config" / "positions.yaml",
           "positions:\n  - ticker: AAPL\n    entry_price: 100\n")
    problems = find_forbidden(tmp_path)
    assert any("positions.yaml" in p for p in problems)


def test_allows_config_yaml_inside_defaults(tmp_path):
    _touch(tmp_path / "_internal" / "defaults" / "exits.yaml", "defaults: {}\nbacktest: {}\n")
    assert find_forbidden(tmp_path) == []


def test_flags_data_and_reports_dirs(tmp_path):
    _touch(tmp_path / "_internal" / "reports" / "2026-06-16.md", "briefing")
    _touch(tmp_path / "_internal" / "data" / "wsb_cache.json", "{}")
    problems = find_forbidden(tmp_path)
    assert any("reports" in p for p in problems)
    assert any("data" in p for p in problems)
