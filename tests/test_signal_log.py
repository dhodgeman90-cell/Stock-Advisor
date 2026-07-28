import json

from src import signal_log


def _sigs(congress=None, wsb=None):
    return {
        "congress": congress, "wsb": wsb,
        "analyst": {"rating": "buy", "upside_pct": 12.0},
        "insider": {"net_side": "buy", "n": 3},
        "earnings": {"days_until": 8},
        "short": {"pct_float": 21.0, "fresh": True},
        "revision": {"up": 4, "down": 1},
        "edgar": {"catalyst": True, "catalyst_types": ["2.02"], "as_of": "2026-07-27"},
        "options": {"put_call": 0.42, "total_vol": 5000},
    }


def _rows(*tickers):
    return [({"ticker": t, "score": 71.5}, _sigs(), 88.0) for t in tickers]


def test_logs_one_record_per_enriched_candidate(tmp_path):
    n = signal_log.log_signals(_rows("AAPL", "NVDA"), tmp_path, "2026-07-28")
    assert n == 2
    recs = signal_log.load_signals(tmp_path)
    assert {r["ticker"] for r in recs} == {"AAPL", "NVDA"}
    r = next(r for r in recs if r["ticker"] == "AAPL")
    assert r["date"] == "2026-07-28"
    assert r["base_score"] == 71.5
    assert r["projected_score"] == 88.0
    # raw values are stored VERBATIM — we do not yet know which fields will matter
    assert r["signals"]["analyst"]["upside_pct"] == 12.0
    assert r["signals"]["edgar"]["catalyst_types"] == ["2.02"]
    assert r["signals"]["options"]["put_call"] == 0.42


def test_is_idempotent_per_date_and_ticker(tmp_path):
    signal_log.log_signals(_rows("AAPL"), tmp_path, "2026-07-28")
    assert signal_log.log_signals(_rows("AAPL"), tmp_path, "2026-07-28") == 0
    assert signal_log.log_signals(_rows("AAPL"), tmp_path, "2026-07-29") == 1   # next day is new
    assert len(signal_log.load_signals(tmp_path)) == 2


def test_none_signals_are_preserved_not_dropped(tmp_path):
    # A missing feed is INFORMATION (that signal was unavailable that day). Storing it as
    # null keeps "absent" distinguishable from "present and neutral" at analysis time.
    signal_log.log_signals(_rows("AAPL"), tmp_path, "2026-07-28")
    r = signal_log.load_signals(tmp_path)[0]
    assert "congress" in r["signals"] and r["signals"]["congress"] is None


def test_market_context_is_recorded_once_per_day(tmp_path):
    signal_log.log_signals(_rows("AAPL", "NVDA"), tmp_path, "2026-07-28",
                           context={"regime": "risk_on", "vix": 17.7})
    for r in signal_log.load_signals(tmp_path):
        assert r["context"]["regime"] == "risk_on"


def test_tolerates_a_half_written_line(tmp_path):
    signal_log.log_signals(_rows("AAPL"), tmp_path, "2026-07-28")
    with signal_log.history_path(tmp_path).open("a", encoding="utf-8") as f:
        f.write('{"date": "2026-07-29", "tick\n')       # torn write
    assert len(signal_log.load_signals(tmp_path)) == 1   # skipped, not fatal
    assert signal_log.log_signals(_rows("NVDA"), tmp_path, "2026-07-29") == 1


def test_unserializable_values_do_not_break_the_run(tmp_path):
    class Weird:
        pass
    rows = [({"ticker": "AAA", "score": 50.0}, {"analyst": Weird()}, 50.0)]
    n = signal_log.log_signals(rows, tmp_path, "2026-07-28")
    assert n == 1
    assert isinstance(signal_log.load_signals(tmp_path)[0]["signals"]["analyst"], str)
