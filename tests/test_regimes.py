import pandas as pd

from src import regimes


def _daily_df(start, periods, price=100.0):
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price,
         "Volume": 1_000_000},
        index=idx,
    )


def test_subperiods_covers_selloff_bull_recent_and_full():
    assert set(regimes.SUBPERIODS) >= {"2022_selloff", "2023_24_bull", "2025_26", "full"}
    assert regimes.SUBPERIODS["full"] == (None, None)


def test_slice_histories_clips_to_window_inclusive():
    hist = {"T": _daily_df("2021-06-01", 1200)}      # spans 2021-06 .. ~2024-09
    out = regimes.slice_histories(hist, "2022-01-01", "2022-12-31")
    idx = out["T"].index
    assert str(idx[0].date()) >= "2022-01-01"
    assert str(idx[-1].date()) <= "2022-12-31"


def test_slice_histories_drops_frames_shorter_than_min_history():
    hist = {"short": _daily_df("2022-12-01", 40),    # only ~31 days inside the 2022 window (<60)
            "long": _daily_df("2021-06-01", 1200)}
    out = regimes.slice_histories(hist, "2022-01-01", "2022-12-31")
    assert "long" in out
    assert "short" not in out


def test_slice_histories_does_not_mutate_input():
    df = _daily_df("2021-06-01", 1200)
    before = len(df)
    regimes.slice_histories({"T": df}, "2022-01-01", "2022-12-31")
    assert len(df) == before


def test_slice_histories_open_ended_full_window_keeps_everything():
    hist = {"T": _daily_df("2022-01-01", 300)}
    out = regimes.slice_histories(hist, None, None)
    assert len(out["T"]) == 300
