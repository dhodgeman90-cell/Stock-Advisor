from src import picks
from tests.helpers import make_df


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


def test_load_picks_skips_corrupt_line(tmp_path):
    p = picks.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"date":"2026-06-08","ticker":"AAA","source":"briefing"}\nnot json\n',
                 encoding="utf-8")
    recs = picks.load_picks(tmp_path)
    assert len(recs) == 1 and recs[0]["ticker"] == "AAA"
