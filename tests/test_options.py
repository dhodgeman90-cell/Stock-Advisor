from src import options


def test_parse_call_heavy_is_bullish():
    calls = [{"volume": 800, "openInterest": 500}, {"volume": 200, "openInterest": 300}]
    puts = [{"volume": 100, "openInterest": 400}]
    out = options._parse_options(calls, puts)
    assert out["call_volume"] == 1000 and out["put_volume"] == 100
    assert out["pc_ratio"] == 0.1
    assert out["direction"] == "bullish"


def test_parse_put_heavy_is_bearish():
    calls = [{"volume": 100, "openInterest": 100}]
    puts = [{"volume": 300, "openInterest": 100}]
    out = options._parse_options(calls, puts)
    assert out["pc_ratio"] == 3.0
    assert out["direction"] == "bearish"


def test_parse_balanced_is_neutral():
    calls = [{"volume": 100, "openInterest": 100}]
    puts = [{"volume": 100, "openInterest": 100}]
    out = options._parse_options(calls, puts)
    assert out["direction"] == "neutral"


def test_parse_vol_oi_turnover():
    calls = [{"volume": 150, "openInterest": 50}]
    puts = [{"volume": 50, "openInterest": 50}]
    out = options._parse_options(calls, puts)
    assert out["total_oi"] == 100
    assert out["vol_oi_ratio"] == 2.0       # 200 volume / 100 OI


def test_parse_handles_nan_and_empty():
    out = options._parse_options([{"volume": float("nan"), "openInterest": float("nan")}], [])
    assert out["call_volume"] == 0 and out["pc_ratio"] is None
    assert out["direction"] == "neutral"


def test_get_options_signal_uses_injected_fetch():
    out = options.get_options_signal(
        "AAPL", fetch=lambda t: ([{"volume": 900, "openInterest": 100}],
                                 [{"volume": 100, "openInterest": 100}]))
    assert out["direction"] == "bullish"


def test_get_options_signal_falls_back_on_error():
    def boom(t):
        raise RuntimeError("no chain")
    out = options.get_options_signal("AAPL", fetch=boom)
    assert out == options.NEUTRAL_OPTIONS
