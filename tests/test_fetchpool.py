import time

from src import fetchpool


def test_fetch_map_runs_each_ticker():
    out = fetchpool.fetch_map(["AAPL", "MSFT"], lambda t: t.lower())
    assert out == {"AAPL": "aapl", "MSFT": "msft"}


def test_fetch_map_dedupes_input():
    calls = []
    fetchpool.fetch_map(["AAPL", "AAPL"], lambda t: calls.append(t))
    assert calls == ["AAPL"]


def test_fetch_map_isolates_failures_to_default():
    def maybe_boom(t):
        if t == "BAD":
            raise RuntimeError("network down")
        return 1
    out = fetchpool.fetch_map(["OK", "BAD"], maybe_boom, default=0)
    assert out == {"OK": 1, "BAD": 0}


def test_fetch_map_default_callable_gives_fresh_objects():
    out = fetchpool.fetch_map(["A", "B"], lambda t: 1 / 0, default=dict)
    assert out["A"] == {} and out["B"] == {}
    out["A"]["x"] = 1
    assert out["B"] == {}            # not the same shared dict


def test_fetch_map_empty_input():
    assert fetchpool.fetch_map([], lambda t: t) == {}


def test_fetch_map_logs_dropped_ticker_instead_of_silent():
    logs = []
    fetchpool.fetch_map(["BAD"], lambda t: 1 / 0, default=0, log=logs.append)
    assert logs and "BAD" in logs[0] and "failed" in logs[0]


def test_fetch_map_times_out_slow_call_and_logs():
    logs = []
    out = fetchpool.fetch_map(["SLOW"], lambda t: time.sleep(0.2) or "done",
                              default="D", timeout=0.01, log=logs.append)
    assert out == {"SLOW": "D"} and "timed out" in logs[0]


def test_fetch_map_silent_when_log_none():
    out = fetchpool.fetch_map(["BAD"], lambda t: 1 / 0, default="X", log=None)
    assert out == {"BAD": "X"}       # no crash, no output
