from src import data
from tests.helpers import make_df


def test_validate_accepts_good_data():
    df = make_df(list(range(50, 120)))   # 70 rows, valid prices
    ok, reason = data.validate(df, "GOOD")
    assert ok is True
    assert reason == ""


def test_validate_rejects_too_few_rows():
    df = make_df([10, 11, 12])           # only 3 rows
    ok, reason = data.validate(df, "SHORT")
    assert ok is False
    assert "rows" in reason.lower()


def test_validate_rejects_nonpositive_close():
    df = make_df([10, 0, 12] + list(range(13, 70)))   # contains a 0 close
    ok, reason = data.validate(df, "ZERO")
    assert ok is False


def test_cache_round_trip(tmp_path):
    df = make_df(list(range(50, 120)))
    data.save_cache(df, "RT", tmp_path)
    loaded = data.load_cache("RT", tmp_path)
    assert loaded is not None
    assert list(loaded["Close"]) == list(df["Close"])


def test_load_cache_missing_returns_none(tmp_path):
    assert data.load_cache("NOPE", tmp_path) is None
