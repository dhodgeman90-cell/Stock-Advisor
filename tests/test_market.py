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


# --- macro overlay: yield curve + credit spread ----------------------------
def test_assess_macro_normal_is_neutral():
    out = market._assess_macro(curve=0.82, hy_spread=2.7)
    assert out["macro_regime"] == "neutral"
    assert out["yield_curve"] == 0.82


def test_assess_macro_inverted_curve_is_risk_off():
    out = market._assess_macro(curve=-0.3, hy_spread=3.0)
    assert out["macro_regime"] == "risk_off"
    assert "inverted" in out["macro_hint"]


def test_assess_macro_credit_stress_is_risk_off():
    out = market._assess_macro(curve=1.0, hy_spread=6.5)
    assert out["macro_regime"] == "risk_off"
    assert "credit spread" in out["macro_hint"]


def test_assess_macro_missing_data_is_neutral():
    out = market._assess_macro(curve=None, hy_spread=None)
    assert out["macro_regime"] == "neutral"


def test_get_macro_context_uses_injected_fetch():
    out = market.get_macro_context(fetch=lambda: {"curve": -0.5, "hy_spread": 3.0})
    assert out["macro_regime"] == "risk_off"


def test_get_macro_context_falls_back_on_error():
    def boom():
        raise RuntimeError("down")
    out = market.get_macro_context(fetch=boom)
    assert out["macro_regime"] == "neutral"
