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


def test_load_adjudicator_returns_floats(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "watchlist.yaml").write_text("tickers:\n  - aapl\n", encoding="utf-8")
    (cfg / "weights.yaml").write_text("weights:\n  breakout: 30\n", encoding="utf-8")
    (cfg / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  risk_high: 20\n", encoding="utf-8"
    )
    caps = config.load_adjudicator(cfg)
    assert caps == {"catalyst": 15.0, "risk_high": 20.0}


def test_load_exit_rules_returns_defaults_and_backtest(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "exits.yaml").write_text(
        "defaults:\n"
        "  stop_loss_pct: 8\n"
        "  take_profit_pct: 20\n"
        "  trend_break_fast: 20\n"
        "  trend_break_slow: 50\n"
        "  momentum_fade:\n"
        "    rsi_was_above: 70\n"
        "    volume_dry_ratio: 0.7\n"
        "backtest:\n"
        "  buy_threshold: 65\n"
        "  max_hold_days: 60\n"
        "  window_years: 2\n"
        "  baseline: equal_weight_watchlist\n",
        encoding="utf-8",
    )
    rules = config.load_exit_rules(cfg)
    assert rules["defaults"]["stop_loss_pct"] == 8
    assert rules["backtest"]["buy_threshold"] == 65


def test_load_exit_rules_rejects_missing_sections(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "exits.yaml").write_text("defaults:\n  stop_loss_pct: 8\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_exit_rules(cfg)


def test_load_positions_parses_and_uppercases(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text(
        "positions:\n"
        "  - ticker: nvda\n"
        "    entry_price: 120.5\n"
        "    entry_date: 2026-06-01\n"
        "    shares: 2\n",
        encoding="utf-8",
    )
    positions = config.load_positions(cfg)
    assert len(positions) == 1
    assert positions[0]["ticker"] == "NVDA"
    assert positions[0]["entry_price"] == 120.5
    assert positions[0]["stop_loss_pct"] is None   # no override


def test_load_positions_empty_when_missing_or_blank(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    # no file at all
    assert config.load_positions(cfg) == []
    # present but empty list
    (cfg / "positions.yaml").write_text("positions: []\n", encoding="utf-8")
    assert config.load_positions(cfg) == []


def test_load_positions_rejects_missing_required_fields(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text(
        "positions:\n  - ticker: NVDA\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        config.load_positions(cfg)


def test_load_positions_rejects_missing_positions_key(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text("holdings:\n  - ticker: NVDA\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_positions(cfg)


def test_load_positions_rejects_zero_entry_price(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "positions.yaml").write_text(
        "positions:\n  - ticker: NVDA\n    entry_price: 0\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        config.load_positions(cfg)


def test_load_watchlist_named_loads_suffixed_file(tmp_path):
    (tmp_path / "watchlist_broad.yaml").write_text(
        "tickers:\n  - JNJ\n  - XOM\nsettings:\n  shortlist_size: 5\n", encoding="utf-8")
    wl = config.load_watchlist(config_dir=tmp_path, name="broad")
    assert wl["tickers"] == ["JNJ", "XOM"]


def test_load_positions_reads_trailing_stop_override(tmp_path):
    (tmp_path / "positions.yaml").write_text(
        "positions:\n  - ticker: AAA\n    entry_price: 100\n    trailing_stop_pct: 12\n",
        encoding="utf-8")
    pos = config.load_positions(config_dir=tmp_path)
    assert pos[0]["trailing_stop_pct"] == 12
