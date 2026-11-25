"""docs/preregistration-overlay-drawdown.md — the overlay vs the monthly rule vs buy-and-hold, on SPY."""
import numpy as np
import pandas as pd
import pytest

from src import market, timing_study as ts


def _close(values, start="2010-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_a_stance_earns_the_next_days_return_not_its_own():
    close = _close([100, 110, 121])
    stance = pd.Series([False, True, True], index=close.index)   # in from day 1's close
    eq = ts.equity(close, stance, cost=0.0)
    # day 1's +10% was decided on day 0 (out) -> not earned; day 2's +10% is earned
    assert eq.iloc[-1] == pytest.approx(1.10)


def test_each_switch_pays_the_cost():
    close = _close([100] * 5)
    stance = pd.Series([True, False, True, False, False], index=close.index)
    eq = ts.equity(close, stance, cost=0.001)
    assert eq.iloc[-1] == pytest.approx(0.999 ** 3)             # three switches after day 0


def test_monthly_stance_only_changes_at_month_ends_and_matches_the_shipped_call():
    vals = [100 + 0.1 * i for i in range(260)] + [50] * 60       # crash mid-way
    close = _close(vals, start="2019-01-01")
    st = ts.monthly_stance(close)
    changes = st.index[st.ne(st.shift()) & st.shift().notna()]
    for d in changes:
        prev = st.index[st.index.get_loc(d) - 1]
        assert prev.month != d.month, "monthly rule must only flip on the first day of a month"
    # agreement with what the briefing shows: the stance on the first session of a month
    # equals monthly_trend_call as of that day
    for d in changes:
        call = market.monthly_trend_call(pd.DataFrame({"Close": close}), as_of=str(d.date()))
        assert (call["stance"] == "invested") == bool(st.loc[d])


def test_overlay_stance_is_the_shipped_regime_with_hysteresis():
    close = _close([100 + np.sin(i / 9) * 20 + i * 0.05 for i in range(600)])
    want = market.apply_hysteresis(market.regime_series(pd.DataFrame({"Close": close}))) != "risk_off"
    assert ts.overlay_stance(close).equals(want)


def test_metrics_cagr_and_drawdown():
    eq = pd.Series([1.0, 2.0, 1.0, 1.5], index=pd.to_datetime(
        ["2020-01-01", "2020-06-01", "2020-12-31", "2021-12-31"]))
    m = ts.metrics(eq, switches=2)
    assert m["max_dd"] == pytest.approx(-0.5)
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    assert m["cagr"] == pytest.approx(1.5 ** (1 / years) - 1)
    assert m["switches_per_year"] == pytest.approx(2 / years)


def _row(dd_bh, dd_ov, ret_dd_ov, ret_dd_mo):
    return {"bh": {"max_dd": dd_bh}, "overlay": {"max_dd": dd_ov, "ret_dd": ret_dd_ov},
            "monthly": {"ret_dd": ret_dd_mo}}


def test_verdict_both_pass():
    res = {y: _row(-0.5, -0.3, 0.4, 0.3) for y in (1999, 2003, 2010, 2015)}
    assert ts.verdict(res)["outcome"] == "PROPOSE_OVERLAY"


def test_verdict_drawdown_must_hold_in_every_period():
    res = {y: _row(-0.5, -0.3, 0.4, 0.3) for y in (1999, 2003, 2010, 2015)}
    res[2015] = _row(-0.34, -0.30, 0.4, 0.3)                    # 0.88x, not <= 0.75x
    v = ts.verdict(res)
    assert v["checks"]["A"] is False and v["outcome"] == "RETIRE_OVERLAY"


def test_verdict_works_but_no_better_than_monthly():
    res = {y: _row(-0.5, -0.3, 0.2, 0.3) for y in (1999, 2003, 2010, 2015)}
    assert ts.verdict(res)["outcome"] == "KEEP_MONTHLY"


def test_the_monthly_agreement_check_is_not_vacuous():
    vals = [100 + 0.1 * i for i in range(260)] + [50] * 60
    st = ts.monthly_stance(_close(vals, start="2019-01-01"))
    assert (st.ne(st.shift()) & st.shift().notna()).sum() >= 1


def test_run_on_a_long_synthetic_history_produces_every_period_and_a_verdict():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("1995-01-03", "2026-11-20")
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(idx))), index=idx)
    res = ts.run_on(close)
    assert set(res["per_start"]) == {1999, 2003, 2010, 2015}
    assert res["end"] == pd.Timestamp("2026-10-30")          # last completed month
    assert res["verdict"]["outcome"] in {"PROPOSE_OVERLAY", "KEEP_MONTHLY", "RETIRE_OVERLAY"}
    assert "VERDICT" in ts.render(res)


def test_a_short_history_says_which_starts_it_cannot_support():
    idx = pd.bdate_range("2005-01-03", "2026-11-20")
    res = ts.run_on(pd.Series(np.linspace(100, 400, len(idx)), index=idx))
    # pre-registered: the earliest supported start replaces 1999
    assert set(res["per_start"]) == {2006, 2010, 2015}
    assert any("1999" in n and "2006" in n for n in res["notes"])
