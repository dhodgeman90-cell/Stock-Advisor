import pandas as pd

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


# ---- point-in-time regime series (Phase 1) ----

def _spy(prices):
    idx = pd.date_range("2021-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": 1_000_000}, index=idx)


def test_regime_series_risk_on_when_price_above_stacked_rising_mas():
    prices = [100.0 + i for i in range(300)]          # steadily rising: close > sma50 > sma200
    reg = market.regime_series(_spy(prices))
    assert reg.iloc[-1] == "risk_on"


def test_regime_series_risk_off_when_below_200d_and_deep_drawdown():
    up = [100.0 + i for i in range(200)]              # rise to a 299 peak over 200 bars
    down = [299.0 - 3.0 * i for i in range(80)]       # then crash far below the 200-day MA
    reg = market.regime_series(_spy(up + down))
    assert reg.iloc[-1] == "risk_off"


def test_regime_series_neutral_during_slow_ma_warmup():
    prices = [100.0 + i for i in range(120)]          # < 200 bars -> sma200 NaN -> no signal
    reg = market.regime_series(_spy(prices))
    assert (reg == "neutral").all()


def test_regime_series_is_as_of_stable():
    # The regime at bar k must not change when later bars are appended (no look-ahead).
    prices = [100.0 + 20.0 * (i % 7) - 0.05 * i for i in range(300)]
    df = _spy(prices)
    k = 250
    assert market.regime_series(df.iloc[:k]).iloc[-1] == market.regime_series(df).iloc[k - 1]


def test_apply_hysteresis_ignores_a_single_risk_off_bar():
    raw = pd.Series(["risk_on"] * 5 + ["risk_off"] + ["risk_on"] * 5)
    out = market.apply_hysteresis(raw, confirm_down=3, confirm_up=5)
    assert (out == "risk_on").all()                   # one red bar never cuts exposure


def test_apply_hysteresis_cuts_after_confirm_down_and_restores_after_confirm_up():
    raw = pd.Series(["risk_on"] * 3 + ["risk_off"] * 3 + ["risk_on"] * 5)
    out = market.apply_hysteresis(raw, confirm_down=3, confirm_up=5)
    assert out.iloc[4] == "risk_on"                   # 2 consecutive risk_off: not yet cut
    assert out.iloc[5] == "risk_off"                  # 3rd consecutive risk_off: cut
    assert out.iloc[-2] == "risk_off"                 # only 4 risk_on since: still defensive
    assert out.iloc[-1] == "risk_on"                  # 5th consecutive risk_on: restored
