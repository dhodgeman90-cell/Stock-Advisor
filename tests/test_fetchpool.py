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
