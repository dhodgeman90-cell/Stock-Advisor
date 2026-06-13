from src import market


def test_summarize_breadth_risk_on_when_calm_and_broad():
    out = market._summarize_breadth(
        vix=13.0, vix_prev=14.0,
        sector_changes={"XLK": 1.2, "XLF": 0.8, "XLE": 0.5, "XLV": 0.3, "XLY": 0.9},
    )
    assert out["regime"] == "risk_on"
    assert out["pct_sectors_up"] == 1.0
    assert out["vix_change"] == -1.0


def test_summarize_breadth_risk_off_when_fearful():
    out = market._summarize_breadth(
        vix=30.0, vix_prev=22.0,
        sector_changes={"XLK": -1.2, "XLF": -0.8, "XLE": 0.1, "XLV": -0.3},
    )
    assert out["regime"] == "risk_off"


def test_summarize_breadth_neutral_in_between():
    out = market._summarize_breadth(
        vix=19.0, vix_prev=19.0,
        sector_changes={"XLK": 0.5, "XLF": -0.5},
    )
    assert out["regime"] == "neutral"
    assert out["pct_sectors_up"] == 0.5


def test_get_market_breadth_uses_injected_fetch():
    out = market.get_market_breadth(fetch=lambda: {
        "vix": 12.0, "vix_prev": 15.0,
        "sector_changes": {"XLK": 1.0, "XLF": 1.0, "XLE": 1.0},
    })
    assert out["regime"] == "risk_on"
    assert "regime_hint" in out and out["regime_hint"]


def test_get_market_breadth_falls_back_on_error():
    def boom():
        raise RuntimeError("yf down")
    out = market.get_market_breadth(fetch=boom)
    assert out["regime"] == "neutral"
