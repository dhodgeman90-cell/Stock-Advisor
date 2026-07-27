import pandas as pd
import pytest

from src import backtest

# cost_pct 0 so hand-computed returns are exact; buy_threshold unused (rank_of is a stub).
RULES = {"backtest": {"buy_threshold": 0, "max_hold_days": 60, "cost_pct_per_side": 0.0}}


def _geo(start_price, daily_ret, periods, start="2022-01-01"):
    """A constant-daily-return price frame, so portfolio math is exact by hand."""
    prices = [start_price * (1 + daily_ret) ** i for i in range(periods)]
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": 1_000_000}, index=idx)


def _fixed_rank(order):
    """rank_of stub: constant ranking from {ticker: rank}; None (ineligible) for others."""
    return lambda date, tk, window: order.get(tk)


def test_simulate_portfolio_holds_only_top_n():
    hist = {"A": _geo(100, 0.10, 4), "B": _geo(100, 0.0, 4), "C": _geo(100, -0.10, 4)}
    res = backtest.simulate_portfolio(hist, _fixed_rank({"A": 3, "B": 2, "C": 1}),
                                      RULES, top_n=1, start_i=1)
    assert round(res["equity_curve"][-1], 4) == 1.21     # only A: +10%/day over 2 steps


def test_simulate_portfolio_equal_weights_top_n():
    hist = {"A": _geo(100, 0.10, 4), "B": _geo(100, 0.0, 4), "C": _geo(100, -0.10, 4)}
    res = backtest.simulate_portfolio(hist, _fixed_rank({"A": 3, "B": 2, "C": 1}),
                                      RULES, top_n=2, start_i=1)
    assert round(res["equity_curve"][-1], 4) == 1.1025   # [A,B] equal weight: +5%/day


def test_simulate_portfolio_exposure_gate_to_cash_is_flat():
    hist = {"A": _geo(100, 0.10, 4), "B": _geo(100, 0.0, 4)}
    idx = hist["A"].index
    res = backtest.simulate_portfolio(hist, _fixed_rank({"A": 2, "B": 1}), RULES,
                                      top_n=2, start_i=1,
                                      regime=pd.Series(["risk_off"] * 4, index=idx),
                                      exposure_map={"risk_off": 0.0})
    assert all(round(v, 6) == 1.0 for v in res["equity_curve"])   # 100% cash -> flat
    assert res["exposure_avg"] == 0.0


def test_simulate_portfolio_half_exposure_halves_return():
    hist = {"A": _geo(100, 0.10, 4), "B": _geo(100, 0.0, 4)}
    idx = hist["A"].index
    full = backtest.simulate_portfolio(hist, _fixed_rank({"A": 2, "B": 1}), RULES,
                                       top_n=2, start_i=1)
    half = backtest.simulate_portfolio(hist, _fixed_rank({"A": 2, "B": 1}), RULES,
                                       top_n=2, start_i=1,
                                       regime=pd.Series(["risk_off"] * 4, index=idx),
                                       exposure_map={"risk_off": 0.5})
    assert full["equity_curve"][-1] == pytest.approx(1.05 ** 2)
    assert half["equity_curve"][-1] == pytest.approx(1.025 ** 2)


def test_simulate_portfolio_skips_ineligible_names():
    hist = {"A": _geo(100, 0.10, 4), "B": _geo(100, 0.20, 4)}
    res = backtest.simulate_portfolio(hist, _fixed_rank({"A": 1}), RULES, top_n=2, start_i=1)
    assert round(res["equity_curve"][-1], 4) == round(1.10 ** 2, 4)   # B ineligible, excluded


# ---- regime-overlay validation + kill criterion (Phase 2) ----

def _m(ret, dd):
    return {"return": ret, "return_pretax": ret, "dd": dd,
            "calmar": backtest._ret_per_dd(ret, dd), "exposure_avg": 1.0, "turnover_avg": 0.1}


def _b(ret, dd):
    return {"return": ret, "dd": dd, "calmar": backtest._ret_per_dd(ret, dd)}


def _crash_frame(start="2021-01-01", periods=1500):
    """2021 rise (establishes the 200d MA) -> 2022 crash -> 2023+ recovery."""
    idx = pd.date_range(start, periods=periods, freq="D")
    prices = []
    for ts in idx:
        if ts.year <= 2021:
            prices.append(300.0 + 0.2 * ts.dayofyear)
        elif ts.year == 2022:
            prices.append(360.0 - 0.7 * ts.dayofyear)      # ~360 -> ~105
        else:
            prices.append(110.0 + 0.3 * ts.dayofyear)
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": 1_000_000}, index=idx)


def test_validate_regime_overlay_cuts_exposure_in_2022_only():
    spy = _crash_frame()
    hist = {"A": _crash_frame(), "B": _crash_frame()}
    res = backtest.validate_regime_overlay(hist, spy, _fixed_rank({"A": 2, "B": 1}),
                                           RULES, top_n=2, start_i=60)
    sell = res["per_regime"]["2022_selloff"]
    assert sell["off"]["exposure_avg"] == 1.0          # OFF is always fully invested
    assert sell["on"]["exposure_avg"] < 1.0            # overlay cut exposure in the crash
    bull = res["per_regime"]["2023_24_bull"]
    assert bull["on"]["exposure_avg"] > sell["on"]["exposure_avg"]   # more invested in recovery
    assert "passed" in res["verdict"]


def test_kill_criterion_all_pass():
    pr = {
        "full": {"on": _m(160, -20), "off": _m(150, -22), "bh": _b(240, -34)},
        "2022_selloff": {"on": _m(-4, -18), "off": _m(-20, -25), "bh": _b(-31, -34)},
        "2023_24_bull": {"on": _m(200, -18), "off": _m(210, -20), "bh": _b(255, -20)},
        "2025_26": {"on": _m(45, -20), "off": _m(43, -24), "bh": _b(48, -28)},
    }
    v = backtest._kill_criterion(pr)
    assert v["passed"] is True and all(v["checks"].values())


def test_kill_criterion_fails_when_2022_loses_to_bh():
    pr = {
        "full": {"on": _m(160, -20), "off": _m(150, -22), "bh": _b(240, -34)},
        "2022_selloff": {"on": _m(-35, -30), "off": _m(-20, -25), "bh": _b(-31, -34)},
        "2023_24_bull": {"on": _m(200, -18), "off": _m(210, -20), "bh": _b(255, -20)},
        "2025_26": {"on": _m(45, -20), "off": _m(43, -24), "bh": _b(48, -28)},
    }
    v = backtest._kill_criterion(pr)
    assert v["checks"]["c2_selloff_on_beats_bh"] is False
    assert v["passed"] is False


def test_render_regime_report_shows_criteria_and_verdict():
    pr = {"full": {"on": _m(160, -20), "off": _m(150, -22), "bh": _b(240, -34)},
          "2022_selloff": {"on": _m(-4, -18), "off": _m(-20, -25), "bh": _b(-31, -34)}}
    result = {"per_regime": pr, "verdict": backtest._kill_criterion(pr),
              "exposure_map": backtest.DEFAULT_EXPOSURE_MAP, "n_names": 2}
    text = backtest.render_regime_report(result, "2026-07-27")
    assert "Kill criterion" in text and "Verdict" in text and "2022 selloff" in text
    assert ("PASS" in text or "FAIL" in text)
    assert "not financial advice" in text.lower()
