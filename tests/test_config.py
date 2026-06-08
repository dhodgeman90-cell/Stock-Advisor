from pathlib import Path
import pytest
from src import config


def _write(tmp_path: Path, watchlist: str, weights: str) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "watchlist.yaml").write_text(watchlist, encoding="utf-8")
    (cfg / "weights.yaml").write_text(weights, encoding="utf-8")
    return cfg


def test_load_watchlist_parses_tickers_and_settings(tmp_path):
    cfg = _write(
        tmp_path,
        "tickers:\n  - aapl\n  - nvda\nsettings:\n  shortlist_size: 4\n",
        "weights:\n  breakout: 30\n",
    )
    wl = config.load_watchlist(cfg)
    assert wl["tickers"] == ["AAPL", "NVDA"]   # upper-cased
    assert wl["settings"]["shortlist_size"] == 4


def test_load_watchlist_rejects_empty(tmp_path):
    cfg = _write(tmp_path, "tickers: []\n", "weights:\n  breakout: 30\n")
    with pytest.raises(ValueError):
        config.load_watchlist(cfg)


def test_load_weights_returns_floats(tmp_path):
    cfg = _write(
        tmp_path,
        "tickers:\n  - aapl\n",
        "weights:\n  breakout: 30\n  volume: 30\n",
    )
    w = config.load_weights(cfg)
    assert w == {"breakout": 30.0, "volume": 30.0}
