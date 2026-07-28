from src import picks
from tests.helpers import make_df


# ---- one pick = one row, regardless of how it got logged --------------------
# picks._key used to include `source`, so backfill_from_reports re-ingested picks the live
# run had already written, as source="report". Result: 448 rows for 280 real picks — 168
# duplicates, ~37% inflation of every count and every average the scorecard reports, and the
# reality-check banner tripping its min_matured gate at half the true sample.

def test_a_pick_is_not_relogged_under_a_different_source(tmp_path):
    df = {"AAA": make_df([10.0] * 60)}
    assert picks.log_picks(_ranked()[:1], df, tmp_path, "2026-07-28") == 1
    assert picks.log_picks(_ranked()[:1], df, tmp_path, "2026-07-28", source="report") == 0
    recs = picks.load_picks(tmp_path)
    assert len(recs) == 1
    assert recs[0]["source"] == "briefing"     # the richer live record is the one kept


def test_same_ticker_on_a_different_date_is_still_a_new_pick(tmp_path):
    df = {"AAA": make_df([10.0] * 60)}
    picks.log_picks(_ranked()[:1], df, tmp_path, "2026-07-28")
    assert picks.log_picks(_ranked()[:1], df, tmp_path, "2026-07-29") == 1
    assert len(picks.load_picks(tmp_path)) == 2


def _ranked():
    return [
        {"ticker": "AAA", "final_score": 88.0, "base_score": 70.0,
         "congress": {"net_side": "buy"}},          # smart-money buy -> high conviction
        {"ticker": "BBB", "final_score": 62.0, "base_score": 55.0},
    ]


def test_log_picks_writes_entry_close_and_conviction(tmp_path):
    dfs = {"AAA": make_df([10.0, 11.0, 12.5]), "BBB": make_df([5.0, 5.0, 5.0])}
    n = picks.log_picks(_ranked(), dfs, tmp_path, "2026-06-08")
    assert n == 2
    recs = {r["ticker"]: r for r in picks.load_picks(tmp_path)}
    assert recs["AAA"]["entry_close"] == 12.5     # last close
    assert recs["AAA"]["conviction"] == "high"
    assert recs["BBB"]["conviction"] == "normal"
    assert recs["BBB"]["base_score"] == 55.0


def test_log_picks_is_idempotent_on_date_ticker_source(tmp_path):
    dfs = {"AAA": make_df([10.0, 11.0, 12.5]), "BBB": make_df([5.0, 5.0, 5.0])}
    picks.log_picks(_ranked(), dfs, tmp_path, "2026-06-08")
    added = picks.log_picks(_ranked(), dfs, tmp_path, "2026-06-08")   # same day again
    assert added == 0
    assert len(picks.load_picks(tmp_path)) == 2


def test_log_picks_different_day_appends(tmp_path):
    dfs = {"AAA": make_df([10.0, 11.0, 12.5]), "BBB": make_df([5.0, 5.0, 5.0])}
    picks.log_picks(_ranked(), dfs, tmp_path, "2026-06-08")
    picks.log_picks(_ranked(), dfs, tmp_path, "2026-06-09")
    assert len(picks.load_picks(tmp_path)) == 4


def test_log_picks_handles_missing_df(tmp_path):
    n = picks.log_picks([{"ticker": "ZZZ", "final_score": 70.0, "base_score": 60.0}],
                        {}, tmp_path, "2026-06-09")
    assert n == 1
    assert picks.load_picks(tmp_path)[0]["entry_close"] is None


def test_log_picks_records_fired_signal_keys(tmp_path):
    ranked = [{"ticker": "AAA", "final_score": 88.0, "base_score": 70.0,
               "congress": {"net_side": "buy"},
               "adjustment_detail": [{"key": "congress_buy", "points": 18},
                                     {"key": "catalyst", "points": 15}]}]
    picks.log_picks(ranked, {"AAA": make_df([10.0, 11.0, 12.5])}, tmp_path, "2026-06-08")
    assert picks.load_picks(tmp_path)[0]["signals"] == ["congress_buy", "catalyst"]


def test_log_picks_signals_default_empty_without_detail(tmp_path):
    picks.log_picks([{"ticker": "ZZZ", "final_score": 70.0, "base_score": 60.0}],
                    {}, tmp_path, "2026-06-09")
    assert picks.load_picks(tmp_path)[0]["signals"] == []


def test_load_picks_skips_corrupt_line(tmp_path):
    p = picks.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"date":"2026-06-08","ticker":"AAA","source":"briefing"}\nnot json\n',
                 encoding="utf-8")
    recs = picks.load_picks(tmp_path)
    assert len(recs) == 1 and recs[0]["ticker"] == "AAA"
