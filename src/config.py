from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str, config_dir) -> dict:
    path = Path(config_dir) / name
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"{name} is empty")
    return data


def load_watchlist(config_dir=CONFIG_DIR) -> dict:
    data = _load("watchlist.yaml", config_dir)
    tickers = data.get("tickers")
    if not tickers or not isinstance(tickers, list):
        raise ValueError("watchlist.yaml must contain a non-empty 'tickers' list")
    return {
        "tickers": [str(t).upper() for t in tickers],
        "settings": data.get("settings", {}),
    }


def load_weights(config_dir=CONFIG_DIR) -> dict:
    data = _load("weights.yaml", config_dir)
    weights = data.get("weights")
    if not weights:
        raise ValueError("weights.yaml must contain a 'weights' mapping")
    return {k: float(v) for k, v in weights.items()}


def load_adjudicator(config_dir=CONFIG_DIR) -> dict:
    data = _load("adjudicator.yaml", config_dir)
    caps = data.get("caps")
    if not caps:
        raise ValueError("adjudicator.yaml must contain a 'caps' mapping")
    return {k: float(v) for k, v in caps.items()}
