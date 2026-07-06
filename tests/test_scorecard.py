import pandas as pd

from src import picks, scorecard
from tests.helpers import make_df

# A saved-briefing sample in the real format (briefing.render_briefing), with both a
# "## Top candidates" section and the differently-formatted "## Other scored" section.
SAMPLE_REPORT = """# Stock Advisor — 2026-06-08

**Market regime:** neutral — mixed.

## 📊 Your holdings
_No tracked positions._

## Top candidates
- **AAPL**: 96/100 (base 81)
    - 📰 something something
    - 🚩 risk low: fine
    - adj: +15 catalyst
- **TSLA**: 67/100 (base 60)
    - 🚩 risk medium: careful

## Other scored (below shortlist)
- AMZN: 24/100
- NFLX: 21/100

_Information only — not financial advice._
"""

# Exit rules with hard take-profit so a tiny test frame's exit logic is predictable.
RULES = {
    "defaults": {"stop_loss_pct": 8, "take_profit_pct": 20, "take_profit_mode": "hard",
                 "trend_break_fast": 20, "trend_break_slow": 50,
                 "momentum_fade": {"rsi_was_above": 70, "volume_dry_ratio": 0.7}},
    "backtest": {"max_hold_days": 60, "cost_pct_per_side": 0.0},
}


def _df(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1_000_000] * len(closes)}, index=idx)


# ---- report parser ----

def test_parse_report_extracts_only_top_candidates():
    recs = scorecard.parse_report(SAMPLE_REPORT, "2026-06-08")
    assert [r["ticker"] for r in recs] == ["AAPL", "TSLA"]   # AMZN/NFLX excluded
    assert recs[0]["final_score"] == 96.0 and recs[0]["base_score"] == 81.0
    assert recs[0]["source"] == "report" and recs[0]["entry_close"] is None


def test_backfill_from_reports_is_idempotent_and_skips_non_briefings(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-06-08.md").write_text(SAMPLE_REPORT, encoding="utf-8")
    (reports / "backtest-default-2026-06-08.md").write_text(
        "## Top candidates\n- **ZZZ**: 99/100 (base 99)\n", encoding="utf-8")
    data_dir = tmp_path / "data"

    assert scorecard.backfill_from_reports(reports, data_dir) == 2   # AAPL, TSLA only
    assert scorecard.backfill_from_reports(reports, data_dir) == 0   # idempotent
    tickers = {r["ticker"] for r in picks.load_picks(data_dir)}
    assert tickers == {"AAPL", "TSLA"}                               # backtest-*.md skipped


# ---- price / return math ----

def test_pos_on_or_after_maps_weekend_to_next_trading_bar():
    df = _df(["2026-06-05", "2026-06-08", "2026-06-09"], [10.0, 11.0, 12.0])  # Fri, Mon, Tue
    assert scorecard._pos_on_or_after(df, "2026-06-06") == 1   # Sat -> next bar (Mon)
    assert scorecard._pos_on_or_after(df, "2026-06-08") == 1   # exact match
    assert scorecard._pos_on_or_after(df, "2026-07-01") is None  # after last bar


def test_forward_return_math_and_immaturity():
    df = make_df([100.0, 105.0, 110.0])
    assert round(scorecard.forward_return(df, 0, 2), 1) == 10.0   # 100 -> 110
    assert scorecard.forward_return(df, 0, 5) is None             # not enough bars
    assert round(scorecard.to_date_return(df, 0), 1) == 10.0


def test_grade_pick_computes_alpha_vs_spy():
    dates = ["2026-06-08", "2026-06-09", "2026-06-10"]
    df = _df(dates, [100.0, 100.0, 110.0])    # +10% to date
    spy = _df(dates, [400.0, 400.0, 416.0])   # +4% to date
    g = scorecard.grade_pick(
        {"date": "2026-06-08", "ticker": "T", "final_score": 90.0,
         "conviction": "high", "entry_close": 100.0}, df, spy, RULES)
    assert round(g["ret_todate"], 1) == 10.0
    assert round(g["alpha_todate"], 1) == 6.0      # 10 - 4
    assert g["band"] == ">=80"


def test_grade_pick_reports_error_when_unpriceable():
    g = scorecard.grade_pick({"date": "2026-06-08", "ticker": "T", "final_score": 50.0},
                             None, None, RULES)
    assert g["error"]


# ---- exit-rule simulation (view 2) ----

def test_simulate_exit_fires_stop_loss():
    df = make_df([100.0, 99.0, 90.0])   # -10% on the last bar, past the -8% stop
    sim = scorecard.simulate_exit_from_entry(df, 0, RULES)
    assert sim["status"] == "closed" and sim["reason"] == "stop_loss"
    assert round(sim["return_pct"], 1) == -10.0


def test_simulate_exit_stays_open_when_nothing_fires():
    df = make_df([100.0, 101.0, 102.0])   # drifts up, no stop/target hit
    sim = scorecard.simulate_exit_from_entry(df, 0, RULES)
    assert sim["status"] == "open"


# ---- aggregation ----

def test_summarize_scorecard_splits_by_band_and_cohort():
    graded = [
        {"band": ">=80", "final_score": 90, "ret_5d": 10.0, "alpha_5d": 5.0, "conviction": "high"},
        {"band": ">=80", "final_score": 85, "ret_5d": -2.0, "alpha_5d": -1.0, "conviction": "normal"},
        {"band": "60-79", "final_score": 70, "ret_5d": 4.0, "alpha_5d": 1.0, "conviction": "normal"},
        {"band": "<60", "final_score": 50, "ret_5d": -6.0, "alpha_5d": -8.0, "conviction": "normal"},
    ]
    s = scorecard.summarize_scorecard(graded, "ret_5d", "alpha_5d", buy_threshold=65)
    assert s["n_matured"] == 4
    assert s["by_band"][">=80"]["n"] == 2
    assert round(s["by_band"][">=80"]["summary"]["win_rate"], 0) == 50   # 1 of 2 positive
    assert s["cohort"]["n"] == 3                                          # scores >= 65
    assert round(s["cohort"]["beat_spy_rate"], 0) == 67                  # 2 of 3 alpha > 0


def test_first_per_ticker_keeps_earliest_only():
    graded = [
        {"ticker": "AAA", "date": "2026-06-08"},
        {"ticker": "BBB", "date": "2026-06-08"},
        {"ticker": "AAA", "date": "2026-06-09"},   # re-recommendation -> dropped
        {"ticker": "BBB", "date": "2026-06-10"},   # re-recommendation -> dropped
    ]
    out = scorecard._first_per_ticker(graded)
    assert [g["ticker"] for g in out] == ["AAA", "BBB"]
    assert out[0]["date"] == "2026-06-08"


def test_summarize_scorecard_excludes_immature():
    graded = [
        {"band": ">=80", "final_score": 90, "ret_5d": 10.0, "alpha_5d": 5.0, "conviction": "high"},
        {"band": ">=80", "final_score": 88, "ret_5d": None, "alpha_5d": None, "conviction": "high"},
    ]
    s = scorecard.summarize_scorecard(graded, "ret_5d", "alpha_5d")
    assert s["n_total"] == 2 and s["n_matured"] == 1   # the None pick is excluded


# ---- rendering ----

def test_render_scorecard_report_has_caveat_and_disclaimer():
    graded = [{
        "date": "2026-06-08", "ticker": "AAA", "final_score": 90.0, "conviction": "high",
        "band": ">=80", "entry": 100.0, "entry_date": "2026-06-08",
        "ret_1d": 1.0, "ret_5d": 3.0, "ret_21d": None, "ret_todate": 5.0,
        "alpha_1d": 0.5, "alpha_5d": 1.0, "alpha_21d": None, "alpha_todate": 2.0,
        "sim": {"status": "closed", "reason": "stop_loss", "hold_days": 4, "return_pct": -5.0},
    }]
    forward = {k: scorecard.summarize_scorecard(graded, k, k.replace("ret", "alpha"), 65)
               for k in ("ret_1d", "ret_5d", "ret_21d")}
    result = {"graded": graded, "forward": forward, "forward_unique": forward,
              "n_unique": 1, "sim": scorecard.summarize_sim(graded)}
    text = scorecard.render_scorecard_report(result, "2026-06-24")
    assert "AAA" in text
    assert "Forward return vs SPY" in text
    assert "Independent picks" in text          # dedup block rendered
    assert "not financial advice" in text.lower()
    # html view renders without error and carries the disclaimer too
    html = scorecard.render_scorecard_html(result, "2026-06-24")
    assert "Independent picks" in html
    assert "not financial advice" in html.lower()


def test_summary_from_graded_flags_underperformance_and_gates_sample():
    # 30 matured picks, cohort alpha negative -> underperforming, enough at floor 30.
    graded = [{"final_score": 90, "band": ">=80", "ret_5d": -1.0, "alpha_5d": -2.0,
               "conviction": "high",
               "sim": {"status": "closed", "reason": "stop_loss", "hold_days": 3,
                       "return_pct": -3.0}} for _ in range(30)]
    s = scorecard.summary_from_graded(graded, buy_threshold=65, n_picks=30, min_matured=30)
    assert s["enough"] is True and s["underperforming"] is True
    assert round(s["cohort_alpha_5d"], 1) == -2.0
    assert round(s["sim_expectancy"], 1) == -3.0


def test_summary_from_graded_withholds_below_floor():
    graded = [{"final_score": 90, "band": ">=80", "ret_5d": 1.0, "alpha_5d": 1.0,
               "conviction": "high",
               "sim": {"status": "open", "reason": "open", "hold_days": 3,
                       "return_pct": 1.0}} for _ in range(5)]
    s = scorecard.summary_from_graded(graded, buy_threshold=65, n_picks=5, min_matured=30)
    assert s["enough"] is False and s["n_matured"] == 5


def test_grade_pick_carries_fired_signals():
    dates = ["2026-06-08", "2026-06-09", "2026-06-10"]
    df = _df(dates, [100.0, 100.0, 110.0])
    spy = _df(dates, [400.0, 400.0, 416.0])
    g = scorecard.grade_pick(
        {"date": "2026-06-08", "ticker": "T", "final_score": 90.0,
         "signals": ["congress_buy", "catalyst"]}, df, spy, RULES)
    assert g["signals"] == ["congress_buy", "catalyst"]


# ---- per-signal attribution (view 3) ----

def test_summarize_by_signal_compares_fired_vs_not_and_gates_thin_samples():
    # 22 picks fire congress_buy with weak alpha; 22 fire catalyst with strong alpha.
    graded = []
    for _ in range(22):
        graded.append({"alpha_5d": -2.0, "ret_5d": -1.0, "signals": ["congress_buy"]})
        graded.append({"alpha_5d": 3.0, "ret_5d": 4.0, "signals": ["catalyst"]})
    by = scorecard.summarize_by_signal(graded, min_fires=20)
    cb = by["congress_buy"]
    assert cb["insufficient"] is False and cb["n_fired"] == 22
    assert round(cb["avg_alpha_fired"], 1) == -2.0
    assert round(cb["avg_alpha_not_fired"], 1) == 3.0     # the catalyst cohort
    assert round(cb["alpha_delta"], 1) == -5.0            # value-destroying signal


def test_summarize_by_signal_flags_insufficient_below_min():
    graded = [{"alpha_5d": 1.0, "ret_5d": 1.0, "signals": ["catalyst"]} for _ in range(5)]
    by = scorecard.summarize_by_signal(graded, min_fires=20)
    assert by["catalyst"]["insufficient"] is True and by["catalyst"]["n_fired"] == 5
    assert "avg_alpha_fired" not in by["catalyst"]        # not scored on a thin sample


def test_render_scorecard_report_shows_signal_attribution_when_present():
    graded = [{"date": "2026-06-08", "ticker": "AAA", "final_score": 90.0, "conviction": "high",
               "band": ">=80", "entry": 100.0, "entry_date": "2026-06-08",
               "ret_1d": 1.0, "ret_5d": 3.0, "ret_21d": None, "ret_todate": 5.0,
               "alpha_1d": 0.5, "alpha_5d": 1.0, "alpha_21d": None, "alpha_todate": 2.0,
               "sim": {"status": "open", "reason": "open", "hold_days": 4, "return_pct": 1.0}}]
    forward = {k: scorecard.summarize_scorecard(graded, k, k.replace("ret", "alpha"), 65)
               for k in ("ret_1d", "ret_5d", "ret_21d")}
    result = {"graded": graded, "forward": forward, "sim": scorecard.summarize_sim(graded),
              "by_signal": {"congress_buy": {"n_fired": 25, "insufficient": False,
                                             "avg_alpha_fired": -2.0, "avg_alpha_not_fired": 1.0,
                                             "alpha_delta": -3.0, "avg_ret_fired": -1.0}}}
    text = scorecard.render_scorecard_report(result, "2026-06-24")
    assert "Signal attribution" in text and "congress_buy" in text


def test_render_scorecard_report_omits_independent_block_when_absent():
    # Back-compat: a result without forward_unique still renders (no dedup section).
    graded = [{"date": "2026-06-08", "ticker": "AAA", "final_score": 90.0,
               "conviction": "high", "band": ">=80", "entry": 100.0, "entry_date": "2026-06-08",
               "ret_1d": 1.0, "ret_5d": 3.0, "ret_21d": None, "ret_todate": 5.0,
               "alpha_1d": 0.5, "alpha_5d": 1.0, "alpha_21d": None, "alpha_todate": 2.0,
               "sim": {"status": "open", "reason": "open", "hold_days": 4, "return_pct": 1.0}}]
    forward = {k: scorecard.summarize_scorecard(graded, k, k.replace("ret", "alpha"), 65)
               for k in ("ret_1d", "ret_5d", "ret_21d")}
    result = {"graded": graded, "forward": forward, "sim": scorecard.summarize_sim(graded)}
    text = scorecard.render_scorecard_report(result, "2026-06-24")
    assert "Independent picks" not in text
    assert "not financial advice" in text.lower()
