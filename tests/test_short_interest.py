"""The pre-registered short-interest study (docs/preregistration-short-interest.md, Amendment 1).

Everything here is offline: the network seams (FINRA, SEC) are injected. The study itself has to
run on the owner's machine, where the price panel and network live.
"""
import math
import random

import numpy as np
import pandas as pd
import pytest

from src import research, short_interest as si


# ---- point-in-time safety ----------------------------------------------------------------

def test_a_reading_is_usable_only_after_publication_never_at_settlement():
    settle = pd.Timestamp("2026-10-15")                       # a Thursday
    usable = si.usable_from(settle)
    assert usable > settle + pd.offsets.BDay(7)              # published on the 7th business day
    assert usable == pd.Timestamp("2026-10-27")              # so usable the session after


def test_signal_panel_never_shows_a_reading_before_it_was_usable():
    rows = pd.DataFrame({"ticker": ["AAA"], "settlement": [pd.Timestamp("2026-10-15")],
                         "short_shares": [1_000.0], "avg_volume": [100.0],
                         "days_to_cover": [10.0]})
    dates = pd.bdate_range("2026-10-10", "2026-11-10")
    shares = {"AAA": [(pd.Timestamp("2026-01-01"), 10_000.0)]}
    ratio, dtc = si.build_signal(rows, shares, dates, ["AAA"])
    assert ratio.loc[:"2026-10-26", "AAA"].isna().all()
    assert ratio.loc["2026-10-27", "AAA"] == pytest.approx(0.1)
    assert dtc.loc["2026-10-27", "AAA"] == pytest.approx(10.0)


def test_shares_outstanding_uses_the_filing_date_not_the_period_end():
    rows = pd.DataFrame({"ticker": ["AAA"], "settlement": [pd.Timestamp("2026-01-15")],
                         "short_shares": [1_000.0], "avg_volume": [100.0],
                         "days_to_cover": [10.0]})
    dates = pd.bdate_range("2026-01-20", "2026-03-31")
    # 20,000 shares, period ended Dec 31 but FILED Feb 20 -> unusable before Feb 20
    shares = {"AAA": [(pd.Timestamp("2025-11-01"), 10_000.0),
                      (pd.Timestamp("2026-02-20"), 20_000.0)]}
    ratio, _ = si.build_signal(rows, shares, dates, ["AAA"])
    assert ratio.loc["2026-02-19", "AAA"] == pytest.approx(0.1)
    assert ratio.loc["2026-02-20", "AAA"] == pytest.approx(0.05)


def test_a_reading_goes_stale_rather_than_being_carried_forever():
    rows = pd.DataFrame({"ticker": ["AAA"], "settlement": [pd.Timestamp("2026-01-15")],
                         "short_shares": [1_000.0], "avg_volume": [100.0],
                         "days_to_cover": [10.0]})
    dates = pd.bdate_range("2026-01-20", "2026-06-30")
    ratio, _ = si.build_signal(rows, {"AAA": [(pd.Timestamp("2025-12-01"), 1e4)]}, dates, ["AAA"])
    assert not math.isnan(ratio.loc["2026-02-10", "AAA"])
    assert ratio.loc["2026-04-30":, "AAA"].isna().all()


def test_stale_shares_outstanding_is_missing_not_reused():
    rows = pd.DataFrame({"ticker": ["AAA"], "settlement": [pd.Timestamp("2026-01-15")],
                         "short_shares": [1_000.0], "avg_volume": [100.0],
                         "days_to_cover": [10.0]})
    dates = pd.bdate_range("2026-01-28", "2026-02-10")
    ratio, dtc = si.build_signal(rows, {"AAA": [(pd.Timestamp("2024-06-01"), 1e4)]}, dates, ["AAA"])
    assert ratio["AAA"].isna().all()
    assert dtc["AAA"].notna().any()                          # days-to-cover needs no SEC data


# ---- parsing both FINRA field-name generations -----------------------------------------------

def test_normalise_accepts_the_current_api_field_names():
    recs = [{"symbolCode": "brk.b", "settlementDate": "2026-10-15",
             "currentShortPositionQuantity": "1500", "averageDailyVolumeQuantity": "300",
             "daysToCoverQuantity": "5.0"}]
    df = si.normalise_finra(recs)
    assert list(df["ticker"]) == ["BRK-B"]                    # yfinance spelling
    assert df["short_shares"].iloc[0] == 1500.0
    assert df["settlement"].iloc[0] == pd.Timestamp("2026-10-15")


def test_normalise_accepts_the_legacy_file_column_names_and_na():
    recs = [{"issueSymbolIdentifier": "AAPL", "settlementDate": "2022-06-15",
             "currentShortShareNumber": "100", "averageShortShareNumber": "50",
             "daysToCoverNumber": "N/A"}]
    df = si.normalise_finra(recs)
    assert df["ticker"].iloc[0] == "AAPL" and df["avg_volume"].iloc[0] == 50.0
    assert math.isnan(df["days_to_cover"].iloc[0])


def test_shares_outstanding_parsed_from_the_sec_concept_payload():
    payload = {"units": {"shares": [
        {"end": "2025-12-31", "val": 100, "filed": "2026-02-01"},
        {"end": "2025-09-30", "val": 90, "filed": "2025-11-01"}]}}
    assert si.shares_outstanding_series(payload) == [
        (pd.Timestamp("2025-11-01"), 90.0), (pd.Timestamp("2026-02-01"), 100.0)]
    assert si.shares_outstanding_series({}) == []


# ---- the vectorised panel IC must agree with the reviewed row-based one ------------------------

def _random_panel(n_days=80, n_names=25, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    names = [f"T{i}" for i in range(n_names)]
    rets = rng.normal(0, 0.02, (n_days, n_names))
    closes = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=names)
    volumes = pd.DataFrame(rng.uniform(2e5, 5e6, (n_days, n_names)), index=idx, columns=names)
    bench = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n_days)), index=idx)
    signal = pd.DataFrame(rng.normal(size=(n_days, n_names)), index=idx, columns=names)
    return signal, closes, volumes, bench


def _rows_from_panel(signal, closes, volumes, bench, h):
    rows = []
    for t in closes.columns:
        df = pd.DataFrame({"Close": closes[t], "Volume": volumes[t]})
        for i, d in enumerate(closes.index):
            if i + h >= len(closes):
                continue
            fwd = (closes[t].iloc[i + h] / closes[t].iloc[i] - 1) - \
                  (bench.iloc[i + h] / bench.iloc[i] - 1)
            rows.append({"date": d.strftime("%Y-%m-%d"), "ticker": t,
                         "sig": float(signal.loc[d, t]), f"fwd_{h}": fwd,
                         "size": research._size(df, i), "vol": research._vol(df["Close"], i)})
    return rows


@pytest.mark.parametrize("neutralize", [False, True])
def test_panel_rank_ic_matches_the_row_based_rank_ic(neutralize):
    signal, closes, volumes, bench = _random_panel()
    h = 5
    want = research.rank_ic(_rows_from_panel(signal, closes, volumes, bench, h), "sig", h,
                            neutralize=neutralize, min_names=10)
    got = research.panel_rank_ic(signal, closes, volumes, bench, horizons=(h,),
                                 neutralize=neutralize, min_names=10, min_dollar_volume=0)[h]
    assert got["n_days"] == want["n_days"]
    assert got["ic"] == pytest.approx(want["ic"], abs=1e-9)
    assert got["t"] == pytest.approx(want["t"], abs=1e-9)


def test_panel_rank_ic_applies_the_dollar_volume_gate_point_in_time():
    signal, closes, volumes, bench = _random_panel()
    volumes.iloc[:, :20] = 1.0                               # 20 of 25 names are untradeable
    got = research.panel_rank_ic(signal, closes, volumes, bench, horizons=(5,),
                                 min_names=10, min_dollar_volume=10_000_000)[5]
    assert got["n_days"] == 0


def test_panel_rank_ic_can_exclude_a_window_and_split_by_year():
    signal, closes, volumes, bench = _random_panel(n_days=300)
    full = research.panel_rank_ic(signal, closes, volumes, bench, horizons=(5,),
                                  min_names=10, min_dollar_volume=0, by_year=True)[5]
    cut = research.panel_rank_ic(signal, closes, volumes, bench, horizons=(5,), min_names=10,
                                 min_dollar_volume=0,
                                 exclude=("2024-03-01", "2024-03-31"))[5]
    assert cut["n_days"] == full["n_days"] - len(pd.bdate_range("2024-03-01", "2024-03-31"))
    assert 2024 in full["by_year"]


def test_a_signal_equal_to_the_forward_return_scores_a_perfect_ic():
    _, closes, volumes, bench = _random_panel()
    fwd = closes.shift(-5) / closes - 1
    signal = fwd.sub(bench.shift(-5) / bench - 1, axis=0)
    got = research.panel_rank_ic(signal, closes, volumes, bench, horizons=(5,),
                                 min_names=10, min_dollar_volume=0)[5]
    assert got["ic"] == pytest.approx(1.0)


# ---- the pre-registered verdict ---------------------------------------------------------------

def _res(ic, t, years):
    return {"ic": ic, "t": t, "n_days": 1000, "hit_rate": 0.5,
            "by_year": {y: {"ic": v, "t": None, "n_days": 250, "hit_rate": 0.5}
                        for y, v in years.items()}}


def test_verdict_passes_only_when_all_four_checks_pass():
    good = _res(0.03, 3.1, {2022: .02, 2023: .04, 2024: .01, 2025: .03, 2026: -.01})
    assert si.verdict(good)["outcome"] == "PASS"


def test_verdict_wrong_sign_is_rejection_not_a_finding():
    bad = _res(-0.01, -0.8, {2022: -.02, 2023: .01, 2024: -.01, 2025: .0})
    assert si.verdict(bad)["outcome"] == "REJECTED"


def test_verdict_negative_and_significant_is_recorded_and_stops():
    v = si.verdict(_res(-0.04, -3.5, {2022: -.03, 2023: -.05, 2024: -.02, 2025: -.04}))
    assert v["outcome"] == "NEGATIVE_SIGNIFICANT"


def test_verdict_right_sign_and_size_but_weak_t_is_underpowered_not_supported():
    v = si.verdict(_res(0.03, 2.1, {2022: .02, 2023: .04, 2024: .01, 2025: .03}))
    assert v["outcome"] == "UNDERPOWERED"


def test_verdict_counts_only_full_years_2022_to_2025():
    # 2026 positive must not rescue a 2-of-4 record
    v = si.verdict(_res(0.03, 3.1, {2021: .05, 2022: .02, 2023: -.04, 2024: -.01,
                                    2025: .03, 2026: .09}))
    assert v["checks"]["years"] is False


def test_verdict_small_ic_fails_the_economic_floor():
    v = si.verdict(_res(0.01, 3.5, {2022: .01, 2023: .01, 2024: .01, 2025: .01}))
    assert v["checks"]["size"] is False and v["outcome"] == "REJECTED"


# ---- fetch seams ------------------------------------------------------------------------------

def test_fetch_finra_pages_filters_to_the_universe_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "FINRA_PAGE", 2)
    calls = []

    def post(url, body):
        calls.append(body["offset"])
        rows = [{"symbolCode": s, "settlementDate": "2022-01-14",
                 "currentShortPositionQuantity": 10, "averageDailyVolumeQuantity": 5,
                 "daysToCoverQuantity": 2} for s in ("AAA", "ZZZ", "BBB")]
        return rows[body["offset"]:body["offset"] + 2]

    df = si.fetch_finra("2022-01-01", "2022-01-31", ["AAA", "BBB"], tmp_path, post=post)
    assert calls == [0, 2]
    assert sorted(df["ticker"]) == ["AAA", "BBB"]
    again = si.fetch_finra("2022-01-01", "2022-01-31", ["AAA", "BBB"], tmp_path,
                           post=lambda *a: pytest.fail("past months come from cache"))
    assert len(again) == 2


def test_fetch_shares_uses_the_cik_map_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    payload = {"units": {"shares": [{"val": 100, "filed": "2025-02-01"}]}}
    out = si.fetch_shares(["AAA", "NOCIK"], {"AAA": 42}, tmp_path / "s.json",
                          get=lambda url: payload)
    assert out["AAA"] == [(pd.Timestamp("2025-02-01"), 100.0)] and out["NOCIK"] == []
    again = si.fetch_shares(["AAA"], {"AAA": 42}, tmp_path / "s.json",
                            get=lambda url: pytest.fail("cached"))
    assert again["AAA"] == out["AAA"]
