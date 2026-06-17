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


def test_uppercase_dotenv_is_caught(tmp_path):
    # Windows is case-insensitive; a .ENV with NO secret marker inside must still be
    # caught by the filename rule (not only by the content scan).
    _touch(tmp_path / "_internal" / ".ENV", "SOME_VAR=value\n")
    assert find_forbidden(tmp_path) != []


def test_nonexistent_dist_dir_is_a_problem_not_clean(tmp_path):
    missing = tmp_path / "nope"
    assert find_forbidden(missing) != []   # must NOT silently report clean


def test_flags_logs_dir(tmp_path):
    _touch(tmp_path / "_internal" / "logs" / "briefing.log", "nothing secret here")
    assert any("logs" in p for p in find_forbidden(tmp_path))


def test_flags_bundled_config_dir(tmp_path):
    # The owner's real config/ dir (vs bundled defaults/) must never ship.
    _touch(tmp_path / "_internal" / "config" / "weights.yaml", "weights: {}\n")
    problems = find_forbidden(tmp_path)
    assert any("config" in p for p in problems)


def test_flags_watchlist_broad_outside_defaults(tmp_path):
    # watchlist_broad.yaml is an owner config file too — caught outside defaults/.
    _touch(tmp_path / "_internal" / "stuff" / "watchlist_broad.yaml", "tickers:\n  - XLF\n")
    problems = find_forbidden(tmp_path)
    assert any("watchlist_broad.yaml" in p for p in problems)
