"""Tests for the rank-IC harness.

These pin the statistics themselves against cases whose answer is known by hand, so a future
signal study cannot be wrong in the measuring rather than in the signal.
"""
import json

import pytest

from src import research
from tests.helpers import make_df


# ============================== rank_ic ==============================

def _rows(day_signal_return_triples):
    """[(date, signal, fwd_5d), ...] -> panel rows shaped like forward_panel output."""
    out = []
    for i, (date, sig, ret) in enumerate(day_signal_return_triples):
        out.append({"date": date, "ticker": f"T{i}", "cohort": "candidate",
                    "base_score": sig, "fwd_5": ret, "size": 0.0, "vol": 0.0})
    return out


def _monotone_day(date, n=20, reverse=False):
    return [(date, float(i), float(-i if reverse else i)) for i in range(n)]


def test_perfectly_ordered_signal_scores_ic_of_one():
    rows = _rows(sum((_monotone_day(f"2026-08-{d:02d}") for d in range(3, 13)), []))
    out = research.rank_ic(rows, "base_score", 5)
    assert out["ic"] == pytest.approx(1.0)
    assert out["n_days"] == 10
    assert out["hit_rate"] == pytest.approx(1.0)


def test_perfectly_inverted_signal_scores_ic_of_minus_one():
    rows = _rows(sum((_monotone_day(f"2026-08-{d:02d}", reverse=True) for d in range(3, 13)), []))
    assert research.rank_ic(rows, "base_score", 5)["ic"] == pytest.approx(-1.0)


def test_ic_is_averaged_per_day_not_pooled_across_days():
    # Day A ranks perfectly, day B perfectly inverted -> the honest answer is 0, and it must
    # not be contaminated by the two days sitting at different return levels.
    rows = _rows(_monotone_day("2026-08-03") + _monotone_day("2026-08-04", reverse=True))
    rows += _rows(_monotone_day("2026-08-05") + _monotone_day("2026-08-06", reverse=True))
    assert research.rank_ic(rows, "base_score", 5)["ic"] == pytest.approx(0.0, abs=1e-9)


def test_days_with_too_few_names_are_dropped_not_silently_averaged():
    rows = _rows(_monotone_day("2026-08-03", n=20) + _monotone_day("2026-08-04", n=3))
    assert research.rank_ic(rows, "base_score", 5, min_names=10)["n_days"] == 1


def test_too_few_days_reports_no_t_stat_rather_than_a_fake_one():
    # A t-stat on 2 overlapping cross-sections is meaningless; it must come back None.
    rows = _rows(_monotone_day("2026-08-03") + _monotone_day("2026-08-04"))
    out = research.rank_ic(rows, "base_score", 5)
    assert out["n_days"] == 2
    assert out["t"] is None
    assert out["ic"] is not None      # the point estimate still stands


def test_t_stat_is_withheld_when_the_windows_barely_overlap_independently():
    # 12 cross-sections is plenty for a 5-day horizon but nowhere near enough for a 21-day one:
    # 12/21 is under one non-overlapping window. On the live data that regime produced t=+29.4
    # on 9 days -- a number that reads as overwhelming evidence and means nothing.
    # ICs must actually vary day to day, or the series has no sampling variance and every
    # horizon correctly reports no t.
    rows = []
    for k, d in enumerate(range(3, 15)):
        rets = list(range(20))
        if k % 2:                       # swap a pair so this day's IC is just under 1.0
            rets[5], rets[6] = rets[6], rets[5]
        for i in range(20):
            rows.append({"date": f"2026-08-{d:02d}", "ticker": f"T{i}", "cohort": "candidate",
                         "base_score": float(i), "fwd_5": float(rets[i]),
                         "fwd_21": float(rets[i]), "size": 0.0, "vol": 0.0})
    assert research.rank_ic(rows, "base_score", 5)["t"] is not None
    slow = research.rank_ic(rows, "base_score", 21)
    assert slow["n_days"] == 12
    assert slow["t"] is None


def test_nested_signal_paths_resolve_and_missing_ones_are_skipped():
    rows = []
    for i in range(20):
        rows.append({"date": "2026-08-03", "ticker": f"T{i}", "cohort": "candidate",
                     "signals": {"analyst": {"upside_pct": float(i)}},
                     "fwd_5": float(i), "size": 0.0, "vol": 0.0})
    rows.append({"date": "2026-08-03", "ticker": "NOPE", "cohort": "candidate",
                 "signals": {"analyst": None}, "fwd_5": 99.0, "size": 0.0, "vol": 0.0})
    out = research.rank_ic(rows, "signals.analyst.upside_pct", 5)
    assert out["ic"] == pytest.approx(1.0)      # the null row was skipped, not coerced to 0


# ============================== neutralize ==============================

_DAYS = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",
         "2026-08-07", "2026-08-10", "2026-08-11", "2026-08-12")


def _panel(signal_of, return_of, size_of, vol_of, n=20):
    return [{"date": d, "ticker": f"T{i}", "cohort": "candidate",
             "base_score": float(signal_of(i)), "fwd_5": float(return_of(i)),
             "size": float(size_of(i)), "vol": float(vol_of(i))}
            for d in _DAYS for i in range(n)]


def test_a_signal_that_is_pure_size_has_no_edge_left_after_neutralising():
    # This is the options.vol_oi_ratio case from the live data: raw IC +0.070/+0.094, and
    # +0.007/-0.003 once size is projected out. Signal and return are both just size here, so
    # the raw IC is a perfect 1.0 and the neutralised one must be exactly 0.
    rows = _panel(signal_of=lambda i: i, return_of=lambda i: i,
                  size_of=lambda i: i, vol_of=lambda i: (i * 7) % 20)
    assert research.rank_ic(rows, "base_score", 5)["ic"] == pytest.approx(1.0)
    assert research.rank_ic(rows, "base_score", 5,
                            neutralize=True)["ic"] == pytest.approx(0.0, abs=1e-6)


def test_neutralising_leaves_a_genuinely_independent_signal_alone():
    # The signal drives the return and is unrelated to size/vol -> the edge must survive intact.
    rows = _panel(signal_of=lambda i: (i * 11) % 20, return_of=lambda i: (i * 11) % 20,
                  size_of=lambda i: i, vol_of=lambda i: (i * 3) % 20)
    assert research.rank_ic(rows, "base_score", 5, neutralize=True)["ic"] > 0.9


def test_a_flat_control_is_dropped_rather_than_killing_the_day():
    # vol is constant (a thin name can do this) -> it is collinear with the intercept. The day
    # must still be measured against size, not silently discarded.
    rows = _panel(signal_of=lambda i: (i * 11) % 20, return_of=lambda i: (i * 11) % 20,
                  size_of=lambda i: i, vol_of=lambda i: 0.0)
    out = research.rank_ic(rows, "base_score", 5, neutralize=True)
    assert out["n_days"] == len(_DAYS)
    assert out["ic"] > 0.9


# ============================== cohort_contrast ==============================

def test_cohort_contrast_measures_candidates_against_the_control_draw():
    rows = []
    for d in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
              "2026-08-10", "2026-08-11", "2026-08-12"):
        for i in range(10):
            rows.append({"date": d, "ticker": f"C{i}", "cohort": "candidate",
                         "base_score": 1.0, "fwd_5": 0.02, "size": 0.0, "vol": 0.0})
            rows.append({"date": d, "ticker": f"X{i}", "cohort": "control",
                         "base_score": 1.0, "fwd_5": 0.01, "size": 0.0, "vol": 0.0})
    out = research.cohort_contrast(rows, 5, min_names=5)
    assert out["candidate"] == pytest.approx(0.02)
    assert out["control"] == pytest.approx(0.01)
    assert out["diff"] == pytest.approx(0.01)
    assert out["n_days"] == 8


# ============================== forward_panel ==============================

def _write_history(tmp_path, ticker, closes, volume=10_000_000):
    df = make_df(closes, volume=volume)
    (tmp_path / f"{ticker}.csv").write_text(df.to_csv(), encoding="utf-8")
    return df


def test_forward_panel_joins_signals_to_prices_and_is_excess_of_the_benchmark(tmp_path):
    # AAA rises 10% over 5 bars while SPY is flat -> +10% excess.
    _write_history(tmp_path, "AAA", [100.0] * 30 + [110.0] * 30)
    _write_history(tmp_path, "SPY", [400.0] * 60)
    entry = make_df([0.0] * 60).index[29].strftime("%Y-%m-%d")
    (tmp_path / "signal_history.jsonl").write_text(
        json.dumps({"date": entry, "ticker": "AAA", "base_score": 50.0,
                    "cohort": "candidate", "signals": {}}) + "\n", encoding="utf-8")

    rows = research.forward_panel(tmp_path, horizons=(5,))
    assert len(rows) == 1
    assert rows[0]["fwd_5"] == pytest.approx(0.10, abs=1e-9)
    assert rows[0]["ticker"] == "AAA" and rows[0]["cohort"] == "candidate"


def test_forward_panel_drops_rows_whose_forward_window_has_not_closed_yet(tmp_path):
    # An entry 2 bars from the end cannot have a 5-day forward return. It must be dropped,
    # never truncated to whatever bars happen to exist -- that would silently shorten the
    # horizon and bias the most recent (and most interesting) rows.
    _write_history(tmp_path, "AAA", [100.0] * 60)
    _write_history(tmp_path, "SPY", [400.0] * 60)
    idx = make_df([0.0] * 60).index
    recs = [{"date": idx[50].strftime("%Y-%m-%d"), "ticker": "AAA", "base_score": 50.0,
             "cohort": "candidate", "signals": {}},
            {"date": idx[57].strftime("%Y-%m-%d"), "ticker": "AAA", "base_score": 50.0,
             "cohort": "candidate", "signals": {}}]
    (tmp_path / "signal_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

    rows = research.forward_panel(tmp_path, horizons=(5,))
    assert [r["date"] for r in rows] == [idx[50].strftime("%Y-%m-%d")]


def test_forward_panel_computes_size_and_volatility_controls(tmp_path):
    # a big, calm name and a small, jumpy one on the same day
    _write_history(tmp_path, "BIG", [100.0] * 60, volume=50_000_000)
    _write_history(tmp_path, "SML", [10.0 + (i % 2) for i in range(60)], volume=100_000)
    _write_history(tmp_path, "SPY", [400.0] * 60)
    entry = make_df([0.0] * 60).index[40].strftime("%Y-%m-%d")
    recs = [{"date": entry, "ticker": t, "base_score": 50.0, "cohort": "candidate",
             "signals": {}} for t in ("BIG", "SML")]
    (tmp_path / "signal_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

    rows = {r["ticker"]: r for r in research.forward_panel(tmp_path, horizons=(5,))}
    assert rows["BIG"]["size"] > rows["SML"]["size"]     # log dollar volume
    assert rows["SML"]["vol"] > rows["BIG"]["vol"]       # realised volatility


def test_forward_panel_survives_a_ticker_with_no_cached_prices(tmp_path):
    _write_history(tmp_path, "AAA", [100.0] * 60)
    _write_history(tmp_path, "SPY", [400.0] * 60)
    entry = make_df([0.0] * 60).index[40].strftime("%Y-%m-%d")
    recs = [{"date": entry, "ticker": t, "base_score": 50.0, "cohort": "candidate",
             "signals": {}} for t in ("AAA", "GONE")]
    (tmp_path / "signal_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")

    rows = research.forward_panel(tmp_path, horizons=(5,))
    assert [r["ticker"] for r in rows] == ["AAA"]


# ============================== panel_ic (long-history test) ==============================
# The 6-week signal_history window put base_score at 5d IC -0.078. The same test on the
# restored ~7-year price panel (1,773 daily cross-sections) puts it at -0.0049. The short
# window overstated the effect ~16x. panel_ic is what makes the well-powered version routine.

def _panels(n_dates=400, n_names=60, informative=False):
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2020-01-01", periods=n_dates, freq="B")
    cols = [f"T{i}" for i in range(n_names)]
    rng = np.random.default_rng(0)
    scores = pd.DataFrame(rng.random((n_dates, n_names)) * 100, index=idx, columns=cols)
    if informative:
        # tomorrow's return is the score -> IC must come back ~1
        step = 1.0 + scores.shift(1).fillna(50.0) / 10000.0
        closes = step.cumprod() * 100.0
    else:
        closes = pd.DataFrame(
            100.0 * np.cumprod(1 + rng.normal(0, 0.01, (n_dates, n_names)), axis=0),
            index=idx, columns=cols)
    bench = pd.Series(100.0, index=idx)
    return scores, closes, bench


def test_panel_ic_recovers_a_signal_that_really_does_predict():
    scores, closes, bench = _panels(informative=True)
    out = research.panel_ic(scores, closes, bench, horizons=(1,))
    assert out[1]["ic"] > 0.9
    assert out[1]["n_days"] > 300


def test_panel_ic_reports_about_zero_for_a_signal_that_does_not():
    scores, closes, bench = _panels(informative=False)
    out = research.panel_ic(scores, closes, bench, horizons=(5,))
    assert abs(out[5]["ic"]) < 0.05          # noise in, noise out
    assert out[5]["n_days"] > 300


def test_panel_ic_splits_by_year_so_a_one_window_artefact_is_visible():
    scores, closes, bench = _panels(informative=True)
    out = research.panel_ic(scores, closes, bench, horizons=(1,), by_year=True)
    years = out[1]["by_year"]
    assert set(years) >= {2020, 2021}
    assert all(v["ic"] > 0.9 for v in years.values())


def test_panel_ic_ignores_days_with_too_thin_a_cross_section():
    scores, closes, bench = _panels(informative=True)
    scores.iloc[:50, 5:] = float("nan")      # 50 days with only 5 scored names
    out = research.panel_ic(scores, closes, bench, horizons=(1,), min_names=30)
    assert out[1]["n_days"] < len(scores) - 49
