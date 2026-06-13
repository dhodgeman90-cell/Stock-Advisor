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


SIGNAL_DEFAULTS = {
    "thresholds": {
        "congress_large_usd": 50000,   # disclosure size that counts as a "big" trade
        "social_min_mentions": 25,     # WSB mentions below which buzz is ignored
        "earnings_window_days": 5,     # demote new entries with earnings within N days
    },
    "discovery": {
        "congress_lookback_days": 30,  # how recent a disclosure must be to surface
        "top_n": 8,                    # max rows in the "outside the watchlist" feed
    },
}


def load_signals(config_dir=CONFIG_DIR) -> dict:
    """Load tunables for the new signal sources, merged over built-in defaults.

    A missing signals.yaml (or any missing key) falls back to SIGNAL_DEFAULTS so the
    briefing always has sane thresholds without requiring the file to exist.
    """
    merged = {section: dict(vals) for section, vals in SIGNAL_DEFAULTS.items()}
    path = Path(config_dir) / "signals.yaml"
    if not path.exists():
        return merged
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for section, vals in data.items():
        if isinstance(vals, dict):
            merged.setdefault(section, {}).update(vals)
        else:
            merged[section] = vals
    return merged


def load_exit_rules(config_dir=CONFIG_DIR) -> dict:
    data = _load("exits.yaml", config_dir)
    defaults = data.get("defaults")
    backtest = data.get("backtest")
    if not defaults or not backtest:
        raise ValueError("exits.yaml must contain 'defaults' and 'backtest' mappings")
    return {"defaults": defaults, "backtest": backtest}


def load_position_overrides(config_dir=CONFIG_DIR) -> dict:
    """Optional per-ticker overrides from positions.yaml, keyed by upper-cased ticker.

    Once SnapTrade supplies live holdings, positions.yaml is demoted to an *overrides*
    file: it no longer needs `entry_price`/`shares`, only the optional knobs you want to
    pin per ticker. Returns only the fields actually present (so a merge won't clobber
    live values with None). Best-effort: a missing/blank file yields {} rather than raising.
    """
    path = Path(config_dir) / "positions.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "positions" not in data:
        return {}
    raw = data["positions"] or []
    overrides = {}
    for p in raw:
        ticker = p.get("ticker")
        if not ticker:
            continue
        fields = {
            k: p[k]
            for k in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct")
            if p.get(k) is not None
        }
        if p.get("entry_date") is not None:
            # YAML parses bare dates into datetime.date; normalize to a string to match
            # load_positions() and the downstream pd.Timestamp(entry_date) usage.
            fields["entry_date"] = str(p["entry_date"])
        if fields:
            overrides[str(ticker).upper()] = fields
    return overrides


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
