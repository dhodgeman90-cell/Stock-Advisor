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


def load_watchlist(config_dir=CONFIG_DIR, name=None) -> dict:
    fname = "watchlist.yaml" if name is None else f"watchlist_{name}.yaml"
    data = _load(fname, config_dir)
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


def load_exit_rules(config_dir=CONFIG_DIR) -> dict:
    data = _load("exits.yaml", config_dir)
    defaults = data.get("defaults")
    backtest = data.get("backtest")
    if not defaults or not backtest:
        raise ValueError("exits.yaml must contain 'defaults' and 'backtest' mappings")
    return {"defaults": defaults, "backtest": backtest}


def load_positions(config_dir=CONFIG_DIR) -> list:
    path = Path(config_dir) / "positions.yaml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    if "positions" not in data:
        raise ValueError(
            "positions.yaml must contain a 'positions' key "
            "(use 'positions: []' if you hold nothing)"
        )
    raw = data["positions"] or []
    if not isinstance(raw, list):
        raise ValueError("positions.yaml 'positions' must be a list")
    out = []
    for p in raw:
        if "ticker" not in p or "entry_price" not in p:
            raise ValueError("each position requires 'ticker' and 'entry_price'")
        if float(p["entry_price"]) <= 0:
            raise ValueError(f"{p['ticker']}: entry_price must be greater than 0")
        out.append({
            "ticker": str(p["ticker"]).upper(),
            "entry_price": float(p["entry_price"]),
            "entry_date": str(p.get("entry_date", "")),
            "shares": p.get("shares"),
            "stop_loss_pct": p.get("stop_loss_pct"),
            "take_profit_pct": p.get("take_profit_pct"),
            "trailing_stop_pct": p.get("trailing_stop_pct"),
        })
    return out
