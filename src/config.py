from pathlib import Path
import os
import tempfile
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


def load_universe(config_dir=CONFIG_DIR):
    """Broad scan universe from config/universe.txt (one ticker per line, '#' = comment).

    Returns an upper-cased, de-duplicated list, or None when the file is absent (the caller
    then falls back to the watchlist tickers). This is the wide funnel the two-stage scorer
    ranks down to an enrichment shortlist; watchlist.yaml stays the small pinned/settings file.
    """
    path = Path(config_dir) / "universe.txt"
    if not path.exists():
        return None
    out, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out or None


def load_weights(config_dir=CONFIG_DIR) -> dict:
    data = _load("weights.yaml", config_dir)
    weights = data.get("weights")
    if not weights:
        raise ValueError("weights.yaml must contain a 'weights' mapping")
    return {k: float(v) for k, v in weights.items()}


def load_adjudicator_base(config_dir=CONFIG_DIR) -> dict:
    """The hand-set caps only (the prior), ignoring any calibration overlay. src.calibrate
    reads this so repeated runs shrink from the prior, not from an already-shrunk value."""
    data = _load("adjudicator.yaml", config_dir)
    caps = data.get("caps")
    if not caps:
        raise ValueError("adjudicator.yaml must contain a 'caps' mapping")
    return {k: float(v) for k, v in caps.items()}


def load_adjudicator(config_dir=CONFIG_DIR) -> dict:
    """Hand-set caps with the generated calibration overlay applied on top when present.

    The overlay (adjudicator.calibrated.yaml, written by src.calibrate) only *shrinks* caps the
    ledger shows are hurting; the hand-set values stay the prior/fallback. Absent overlay → the
    plain hand-set caps.
    """
    caps = load_adjudicator_base(config_dir)
    path = Path(config_dir) / "adjudicator.calibrated.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
        for k, v in (overlay.get("caps") or {}).items():
            if k in caps:                      # only override caps that already exist
                caps[k] = float(v)
    return caps


def save_calibrated_adjudicator(config_dir, caps, meta=None) -> None:
    """Persist the calibration overlay atomically. `meta` (e.g. generated date, sample size)
    is recorded alongside for provenance but ignored by the loader."""
    payload = {"caps": {k: float(v) for k, v in caps.items()}}
    if meta:
        payload["_meta"] = dict(meta)
    _atomic_write_yaml(Path(config_dir) / "adjudicator.calibrated.yaml", payload)


SIGNAL_DEFAULTS = {
    "thresholds": {
        "congress_large_usd": 50000,   # disclosure size that counts as a "big" trade
        "social_min_mentions": 25,     # WSB mentions below which buzz is ignored
        "earnings_window_days": 5,     # demote new entries with earnings within N days
        "options_unusual_ratio": 0.5,  # option volume / OI above which flow is "unusual"
        "options_min_volume": 1000,    # ignore option flow thinner than this
        "short_high_pct": 20,          # short % of float at/above which squeeze logic applies
        "sec_window_days": 30,         # how recent an SEC filing must be to count
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


def _atomic_write_yaml(path, data) -> None:
    """Write YAML to `path` atomically (temp file + os.replace) so a crash mid-write
    never leaves a half-written config the loaders would choke on."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_watchlist(config_dir, tickers, settings=None) -> None:
    """Persist watchlist.yaml. Tickers are upper-cased and de-duplicated (order kept).
    Mirrors what load_watchlist() expects. NOTE: comments in an existing file are not
    preserved (safe_dump rewrites it) — fine for the per-user profile configs this
    serves; not meant for the owner's hand-annotated repo config/."""
    clean, seen = [], set()
    for t in tickers:
        u = str(t).strip().upper()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    if not clean:
        raise ValueError("watchlist must contain at least one ticker")
    _atomic_write_yaml(Path(config_dir) / "watchlist.yaml",
                       {"tickers": clean, "settings": dict(settings or {})})


def save_positions(config_dir, positions) -> None:
    """Persist positions.yaml in the shape load_positions() reads. Optional fields
    (entry_date, shares, *_pct) are omitted when blank/None to keep the file clean.
    NOTE: comments in an existing file are not preserved (safe_dump rewrites it) —
    fine for the per-user profile configs this serves."""
    out = []
    for p in positions:
        ticker = str(p["ticker"]).strip().upper()
        entry_price = float(p["entry_price"])
        if entry_price <= 0:
            raise ValueError(f"{ticker}: entry_price must be greater than 0")
        row = {"ticker": ticker, "entry_price": entry_price}
        if p.get("entry_date"):
            row["entry_date"] = str(p["entry_date"])
        for k in ("shares", "stop_loss_pct", "take_profit_pct", "trailing_stop_pct"):
            if p.get(k) is not None:
                row[k] = p[k]
        out.append(row)
    _atomic_write_yaml(Path(config_dir) / "positions.yaml", {"positions": out})


INTEGRATION_FIELDS = ("EMAIL_USER", "EMAIL_TO", "EMAIL_HOST", "EMAIL_PORT",
                      "SNAPTRADE_CLIENT_ID", "SNAPTRADE_USER_ID")


def _read_integrations_raw(config_dir) -> dict:
    path = Path(config_dir) / "integrations.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_integrations(config_dir) -> dict:
    """Non-secret integration config from integrations.yaml, keyed by env-var name.

    Secrets (Anthropic key, email app password, SnapTrade consumer key/user secret) are
    NOT here — those live in the OS credential store (see src/secrets_store.py). A
    missing/blank file yields {}.
    """
    data = _read_integrations_raw(config_dir)
    out = {}
    email = data.get("email") or {}
    for env_key, yaml_key in (("EMAIL_USER", "user"), ("EMAIL_TO", "to"),
                              ("EMAIL_HOST", "host"), ("EMAIL_PORT", "port")):
        val = email.get(yaml_key)
        if val is not None and str(val).strip() != "":
            out[env_key] = str(val).strip()
    brokerage = data.get("brokerage") or {}
    for env_key, yaml_key in (("SNAPTRADE_CLIENT_ID", "client_id"),
                              ("SNAPTRADE_USER_ID", "user_id")):
        val = brokerage.get(yaml_key)
        if val is not None and str(val).strip() != "":
            out[env_key] = str(val).strip()
    return out


def _write_integration_section(config_dir, section: str, mapping: dict) -> None:
    """Merge `mapping` into one section of integrations.yaml, preserving other sections.

    A value of None means "leave unchanged"; "" (or blank) means "clear that field";
    any other value is set (stringified + trimmed). Blank fields are never written as
    empty strings, which the engine would misread as 'configured'.
    """
    data = _read_integrations_raw(config_dir)
    sect = dict(data.get(section) or {})
    for key, val in mapping.items():
        if val is None:
            continue
        sval = str(val).strip()
        if sval == "":
            sect.pop(key, None)
        else:
            sect[key] = sval
    if sect:
        data[section] = sect
    else:
        data.pop(section, None)
    _atomic_write_yaml(Path(config_dir) / "integrations.yaml", data)


def save_integrations(config_dir, *, user="", to="", host="", port="") -> None:
    """Persist non-secret email config to the 'email' section of integrations.yaml."""
    _write_integration_section(config_dir, "email",
                               {"user": user, "to": to, "host": host, "port": port})


def save_brokerage_identity(config_dir, *, client_id=None, user_id=None) -> None:
    """Persist the non-secret SnapTrade identifiers to the 'brokerage' section.

    Pass None to leave a field unchanged, "" to clear it. The secret consumer key and
    user secret are stored separately in the OS keyring, not here."""
    _write_integration_section(config_dir, "brokerage",
                               {"client_id": client_id, "user_id": user_id})
