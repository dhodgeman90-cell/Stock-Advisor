import pytest
from src import config


def test_save_watchlist_roundtrips(tmp_path):
    config.save_watchlist(tmp_path, ["aapl", "MSFT", "aapl"],
                          {"shortlist_size": 3, "lookback_days": 120})
    wl = config.load_watchlist(tmp_path)
    assert wl["tickers"] == ["AAPL", "MSFT"]          # upper-cased + de-duped, order kept
    assert wl["settings"]["shortlist_size"] == 3
    assert wl["settings"]["lookback_days"] == 120


def test_save_watchlist_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        config.save_watchlist(tmp_path, [], {})


def test_save_positions_roundtrips(tmp_path):
    config.save_positions(tmp_path, [
        {"ticker": "aapl", "entry_price": 150, "entry_date": "2026-01-02", "shares": 10},
        {"ticker": "msft", "entry_price": 300},
    ])
    pos = config.load_positions(tmp_path)
    assert pos[0]["ticker"] == "AAPL" and pos[0]["entry_price"] == 150.0
    assert pos[0]["entry_date"] == "2026-01-02" and pos[0]["shares"] == 10
    assert pos[1]["ticker"] == "MSFT" and pos[1]["entry_date"] == ""   # omitted -> "" on load


def test_save_positions_empty_writes_loadable_file(tmp_path):
    config.save_positions(tmp_path, [])
    assert config.load_positions(tmp_path) == []


def test_save_positions_rejects_bad_price(tmp_path):
    with pytest.raises(ValueError):
        config.save_positions(tmp_path, [{"ticker": "X", "entry_price": 0}])
