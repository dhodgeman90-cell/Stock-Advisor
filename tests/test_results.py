from pathlib import Path
from src.results import RunResult


def test_runresult_minimal_defaults():
    r = RunResult(date="2026-06-15", text="hello")
    assert r.date == "2026-06-15"
    assert r.text == "hello"
    assert r.html == ""
    assert r.ranked == [] and r.vetoed == [] and r.holdings == []
    assert r.rotation_plan == {} and r.discovery == {}
    assert r.report_path is None
    assert r.skipped is False


def test_runresult_holds_structured_fields():
    r = RunResult(
        date="2026-06-15", text="t", html="<p>t</p>",
        regime="neutral", regime_note="calm",
        ranked=[{"ticker": "AAA"}], report_path=Path("reports/2026-06-15.md"),
    )
    assert r.html == "<p>t</p>"
    assert r.ranked[0]["ticker"] == "AAA"
    assert r.report_path == Path("reports/2026-06-15.md")
