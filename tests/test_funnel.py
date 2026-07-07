"""Phase C — wide-universe two-stage funnel: universe load, batch frame extraction, and the
priority-signal enrichment gate."""
import pandas as pd

from src import config, data, main


# ---- config.load_universe ------------------------------------------------
def test_load_universe_parses_comments_dedupes_and_uppercases(tmp_path):
    (tmp_path / "universe.txt").write_text(
        "# a comment\nAAPL\nmsft  # inline comment\nAAPL\n\nNVDA\n", encoding="utf-8")
    assert config.load_universe(tmp_path) == ["AAPL", "MSFT", "NVDA"]


def test_load_universe_none_when_absent(tmp_path):
    assert config.load_universe(tmp_path) is None


def test_repo_universe_file_has_the_sp500(tmp_path):
    uni = config.load_universe(config.CONFIG_DIR)
    assert uni is not None and len(uni) > 400 and "AAPL" in uni


# ---- data._extract_ticker_frame ------------------------------------------
def _bulk_df(tickers):
    idx = pd.date_range("2026-01-01", periods=3)
    cols = pd.MultiIndex.from_product([tickers, ["Open", "High", "Low", "Close", "Volume"]])
    rows = []
    for i in range(3):
        row = []
        for t_i, _ in enumerate(tickers):
            base = 10 * (t_i + 1) + i
            row += [base, base + 1, base - 1, base + 0.5, 1_000_000]
        rows.append(row)
    return pd.DataFrame(rows, index=idx, columns=cols)


def test_extract_ticker_frame_pulls_one_symbol():
    raw = _bulk_df(["AAA", "BBB"])
    df = data._extract_ticker_frame(raw, "BBB", 2)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df["Close"].iloc[0] == 20.5        # BBB base 20 + 0.5


def test_extract_ticker_frame_missing_symbol_is_none():
    raw = _bulk_df(["AAA", "BBB"])
    assert data._extract_ticker_frame(raw, "ZZZ", 2) is None


# ---- main._has_priority_signal -------------------------------------------
def test_priority_signal_fresh_congress_buy():
    agg = {"X": {"net_side": "buy", "fresh": True}}
    assert main._has_priority_signal("X", agg, {}, 25) is True


def test_priority_signal_stale_congress_ignored():
    agg = {"X": {"net_side": "buy", "fresh": False}}
    assert main._has_priority_signal("X", agg, {}, 25) is False


def test_priority_signal_wsb_surge():
    wsb = {"X": {"mentions": 300, "mentions_change": 120}}
    assert main._has_priority_signal("X", {}, wsb, 25) is True


def test_priority_signal_wsb_below_min_mentions_ignored():
    wsb = {"X": {"mentions": 5, "mentions_change": 120}}
    assert main._has_priority_signal("X", {}, wsb, 25) is False


def test_priority_signal_none_when_no_feeds():
    assert main._has_priority_signal("X", {}, {}, 25) is False
