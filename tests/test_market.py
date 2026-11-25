import numpy as np
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


# ---- monthly 200-day trend call -------------------------------------------------------------
# The one rule in this repo with survivorship-free evidence behind it (docs/results-medium-
# horizon-and-timing.md §1): hold the index while SPY's MONTH-END close is above its 200-day
# average, otherwise cash. Checked monthly — weekly and daily were measured worse (whipsaw).

def _spy(closes, start="2025-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_trend_call_is_invested_when_last_month_end_closed_above_the_200d_average():
    df = _spy([100.0 + 0.1 * i for i in range(300)])       # steady uptrend
    call = market.monthly_trend_call(df, as_of="2026-02-10")
    assert call["stance"] == "invested"
    assert call["decided_on"] == "2026-01-30"                # last bar of the last full month
    assert call["close"] > call["sma"]


def test_trend_call_steps_aside_when_last_month_end_closed_below():
    df = _spy([200.0 - 0.2 * i for i in range(300)])       # steady downtrend
    assert market.monthly_trend_call(df, as_of="2026-02-10")["stance"] == "aside"


def test_a_mid_month_cross_does_not_change_the_call():
    # Uptrend through January, then a crash in February: the call stays "invested" until the
    # February month-end is in. Acting mid-month is exactly the whipsaw that was measured worse.
    df = _spy([100.0 + 0.1 * i for i in range(300)])          # runs into late February 2026
    df.loc[df.index >= "2026-02-01", "Close"] = 50.0
    call = market.monthly_trend_call(df, as_of="2026-02-25")
    assert call["stance"] == "invested"
    assert call["latest_close"] < call["latest_sma"]          # still shown, as information


def test_trend_call_reports_a_change_from_the_previous_month():
    # Uptrend through December, January collapses below the average; February's run switches.
    df = _spy([100.0 + 0.1 * i for i in range(300)])
    df.loc[df.index >= "2026-01-01", "Close"] = 60.0
    call = market.monthly_trend_call(df, as_of="2026-02-03")
    assert call["decided_on"] == "2026-01-30"
    assert call["stance"] == "aside"
    assert call["previous_stance"] == "invested"
    assert call["changed"] is True


def test_steady_call_is_not_reported_as_a_change():
    df = _spy([100.0 + 0.1 * i for i in range(300)])
    call = market.monthly_trend_call(df, as_of="2026-02-10")
    assert call["previous_stance"] == "invested"
    assert call["changed"] is False


def test_trend_call_is_none_without_200_bars_before_the_month_end():
    assert market.monthly_trend_call(_spy([100.0] * 150), as_of="2026-02-10") is None
    assert market.monthly_trend_call(None, as_of="2026-02-10") is None


def test_trend_call_uses_no_bar_from_the_current_month():
    base = [100.0 + 0.1 * i for i in range(300)]
    df = _spy(base)
    a = market.monthly_trend_call(df, as_of="2026-02-10")
    df2 = df.copy()
    df2.loc[df2.index >= "2026-02-01", "Close"] = 1.0          # wreck February only
    b = market.monthly_trend_call(df2, as_of="2026-02-10")
    assert (a["stance"], a["decided_on"], a["close"], a["sma"]) == \
           (b["stance"], b["decided_on"], b["close"], b["sma"])


# ---- the overlay market call (docs/results-overlay-drawdown.md: PROPOSE_OVERLAY, adopted) ----

def test_overlay_call_matches_the_tested_rule_on_the_last_bar():
    rng = np.random.default_rng(1)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, 700))
    df = _spy(list(close), start="2023-01-02")
    want = market.apply_hysteresis(market.regime_series(df)).iloc[-1] != "risk_off"
    call = market.overlay_call(df)
    assert (call["stance"] == "invested") == bool(want)
    assert call["kind"] == "overlay"
    assert call["decided_on"] == str(df.index[-1].date())


def test_overlay_call_steps_aside_in_a_confirmed_downtrend():
    vals = [100.0 + 0.1 * i for i in range(300)] + [130.0 - 1.0 * i for i in range(40)]
    call = market.overlay_call(_spy(vals))
    assert call["stance"] == "aside"
    assert call["dd_from_high"] < -8.0


def test_overlay_call_reports_the_day_it_changed():
    vals = [100.0 + 0.1 * i for i in range(300)] + [130.0 - 1.0 * i for i in range(40)]
    df = _spy(vals)
    regime = market.apply_hysteresis(market.regime_series(df))
    flip = next(i for i in range(1, len(regime)) if regime.iloc[i] != regime.iloc[i - 1])
    on_flip = market.overlay_call(df.iloc[:flip + 1])
    assert on_flip["changed"] is True and on_flip["previous_stance"] == "invested"
    day_after = market.overlay_call(df.iloc[:flip + 2])
    assert day_after["changed"] is False
    assert day_after["since"] == str(df.index[flip].date())


def test_overlay_call_none_without_data():
    assert market.overlay_call(None) is None
    assert market.overlay_call(_spy([100.0] * 50)) is None      # no 200-day average yet
