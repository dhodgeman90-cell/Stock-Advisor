"""Sync current holdings from a brokerage (Robinhood) via the SnapTrade API.

Read-only: this module never places trades. It turns live brokerage positions into
the same position-dict shape that `config.load_positions()` returns, so the rest of
the briefing is unchanged.

Configuration (all in .env, set up once via `python -m src.link_broker`):
    SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY  -> your SnapTrade app keys
    SNAPTRADE_USER_ID, SNAPTRADE_USER_SECRET     -> your SnapTrade connected-user creds
    SNAPTRADE_ACCOUNT_ID (optional)              -> pin one account; else all are aggregated

SnapTrade does brokerage 2FA once at link time, so unattended runs never block on a code.
"""
import json
import os
from datetime import date
from pathlib import Path

from src import config

_REQUIRED_ENV = (
    "SNAPTRADE_CLIENT_ID",
    "SNAPTRADE_CONSUMER_KEY",
    "SNAPTRADE_USER_ID",
    "SNAPTRADE_USER_SECRET",
)


def is_configured() -> bool:
    """True only when every SnapTrade credential is present in the environment."""
    return all(os.environ.get(k) for k in _REQUIRED_ENV)


# ---- SDK seams (thin adapters; the only code that touches the real SnapTrade SDK) ----

def _client():
    from snaptrade_client import SnapTrade

    return SnapTrade(
        consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"],
        client_id=os.environ["SNAPTRADE_CLIENT_ID"],
    )


def _default_list_accounts(client) -> list:
    resp = client.account_information.list_user_accounts(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
    )
    return list(resp.body)


def _default_list_activities(client, account_id, start_date, end_date) -> list:
    # NOTE: account_information.get_account_activities — NOT
    # transactions_and_reporting.get_activities. The latter is the same trap as
    # get_user_holdings below: the SDK marks it deprecated and it returns HTTP 410 Gone on
    # real accounts (verified live 2026-07-28). Do not "modernize" this to the other one.
    resp = client.account_information.get_account_activities(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        limit=1000,
    )
    body = resp.body
    return list(body.get("data", body)) if isinstance(body, dict) else list(body)


def _default_list_positions(client, account_id) -> list:
    # NOTE: use get_user_account_positions, NOT get_user_holdings. The SDK logs the former
    # as "deprecated", but it still works and returns the positions list directly. Its
    # supposed replacement, get_user_holdings, returns HTTP 410 ("no longer available for
    # your account") on real accounts — verified live 2026-06-18 — so switching to it
    # silently broke live holdings (the briefing fell back to positions.yaml). Until
    # SnapTrade ships a working successor, the deprecated-but-functional call is correct.
    resp = client.account_information.get_user_account_positions(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
        account_id=account_id,
    )
    return list(resp.body)


# ---- pure parsing/aggregation (fully unit-tested) ----

def _extract_ticker(pos: dict):
    """Ticker string from a SnapTrade POSITION or ACTIVITY row.

    The two payloads nest differently and both are in use here: a position gives
    symbol.symbol.symbol (a nested universal-symbol object), while an activity gives
    symbol.symbol directly as the ticker string. Handle both rather than duplicating this
    into two near-identical parsers.
    """
    symbol = pos.get("symbol") or {}
    if not isinstance(symbol, dict):
        return None
    universal = symbol.get("symbol")
    if isinstance(universal, str):                       # activity row
        ticker = universal
    else:                                                # position row
        universal = universal or {}
        ticker = universal.get("symbol") or universal.get("raw_symbol")
    ticker = ticker or symbol.get("raw_symbol")
    return str(ticker).upper() if ticker else None


def _aggregate(raw_positions) -> list:
    """Raw SnapTrade positions -> holding dicts, summing shares and share-weighting cost.

    A ticker held across multiple accounts is merged into one position whose entry_price
    is the share-weighted average cost basis. Output matches config.load_positions().
    """
    by_ticker = {}   # ticker -> {"shares": float, "cost": float}
    for p in raw_positions:
        ticker = _extract_ticker(p)
        units = p.get("units")
        if units is None:
            units = p.get("fractional_units")
        avg = p.get("average_purchase_price")
        if not ticker or units is None or avg is None:
            continue
        units = float(units)
        if units == 0:
            continue
        slot = by_ticker.setdefault(ticker, {"shares": 0.0, "cost": 0.0})
        slot["shares"] += units
        slot["cost"] += units * float(avg)

    holdings = []
    for ticker, agg in sorted(by_ticker.items()):
        shares = agg["shares"]
        entry_price = agg["cost"] / shares if shares else 0.0
        holdings.append({
            "ticker": ticker,
            "entry_price": entry_price,
            "shares": shares,
            "entry_date": "",
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "trailing_stop_pct": None,
        })
    return holdings


def fetch_holdings(*, client_factory=_client,
                   list_accounts=_default_list_accounts,
                   list_positions=_default_list_positions) -> list:
    """Pull live holdings from SnapTrade. Raises on failure so callers can fall back.

    The factory/adapters are injectable so tests run against a fake SnapTrade client.
    """
    client = client_factory()
    pinned = os.environ.get("SNAPTRADE_ACCOUNT_ID")
    if pinned:
        account_ids = [pinned]
    else:
        account_ids = [a.get("id") for a in list_accounts(client) if a.get("id")]

    raw = []
    for account_id in account_ids:
        raw.extend(list_positions(client, account_id))
    return _aggregate(raw)


# ---- true entry dates, derived from brokerage activity -------------------------------

ACTIVITY_START = "2015-01-01"   # ask wide; the broker returns whatever history it has


def _activity_units(row):
    """Signed share count for a BUY/SELL row, or None if it isn't a trade."""
    kind = str(row.get("type") or "").upper()
    if kind not in ("BUY", "SELL"):
        return None
    try:
        u = float(row.get("units"))
    except (TypeError, ValueError):
        return None
    # Some brokers report SELL units unsigned; trust the type over the sign.
    return -abs(u) if kind == "SELL" else abs(u)


def _derive_open_dates(activities) -> dict:
    """ticker -> the date its CURRENT position was opened, from a brokerage activity feed.

    Walks each ticker's BUY/SELL rows in date order and records the date the running share
    count last crossed 0 -> >0. That is the definition a position-level trailing stop needs:
    an ADD or a PARTIAL SELL must not reset the high-water clock, but a full exit followed by
    a re-buy must. Tickers currently flat are omitted entirely rather than given a stale date.

    Pure — no I/O — so the edge cases (out-of-order rows, non-trade activity, float dust left
    by fractional-share brokers) are unit-tested directly.
    """
    by_ticker = {}
    for row in activities or []:
        ticker = _extract_ticker(row)
        units = _activity_units(row)
        date = str(row.get("trade_date") or "")[:10]
        if not ticker or units is None or len(date) != 10:
            continue
        by_ticker.setdefault(ticker, []).append((date, units))

    out = {}
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda r: r[0])
        held, opened = 0.0, None
        for date, units in rows:
            was_flat = held <= 1e-9
            held += units
            if was_flat and held > 1e-9:
                opened = date
            elif held <= 1e-9:
                opened = None          # fully closed — the next buy starts a new position
        if opened:
            out[ticker] = opened
    return out


def fetch_entry_dates(*, client_factory=_client,
                      list_accounts=_default_list_accounts,
                      list_activities=_default_list_activities,
                      today=None) -> dict:
    """ticker -> true position-open date, across every linked account. Raises on failure so
    callers can fall back to the first-seen store."""
    client = client_factory()
    pinned = os.environ.get("SNAPTRADE_ACCOUNT_ID")
    account_ids = ([pinned] if pinned
                   else [a.get("id") for a in list_accounts(client) if a.get("id")])
    end = today or date.today().isoformat()
    rows = []
    for account_id in account_ids:
        rows.extend(list_activities(client, account_id, ACTIVITY_START, end))
    return _derive_open_dates(rows)


# ---- first-seen dates (the fallback when activity history doesn't reach) --------------

FIRST_SEEN_FILE = "position_first_seen.json"


def _stamp_first_seen(holdings, data_dir, today) -> list:
    """Fill each holding's `entry_date` from a local ticker -> first-seen-date store.

    SnapTrade positions carry no purchase date, and `_aggregate` therefore emitted
    `entry_date: ""`. That blank silently disabled the two exits that protect a WINNER:
    `main.run` fell back to `peak = entry_price`, which collapses exits.py's trailing-stop
    test to `price <= price * (1 - trail)` — never true — and `exits.py`'s live time-stop is
    gated on a truthy entry_date. Only the 8% catastrophe stop measured from entry survived,
    so a position that doubled and round-tripped to breakeven never emitted a sell.

    First-seen is a LOWER bound on the true holding period for anything bought before the
    store existed, so the peak it yields is a lower bound too and the trailing stop fires
    no EARLIER than it should — conservative, never a false sell. Pin the real date in
    positions.yaml (`entry_date:`) when you know it; that override is merged after this and
    wins. Tickers that leave the book are pruned so a re-buy restarts the clock.
    """
    path = Path(data_dir) / FIRST_SEEN_FILE
    try:
        seen = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(seen, dict):
            seen = {}
    except Exception:   # noqa: BLE001 - missing or corrupt store rebuilds, never breaks a sync
        seen = {}

    held = {p["ticker"] for p in holdings}
    seen = {t: d for t, d in seen.items() if t in held}     # prune closed positions
    for ticker in held:
        seen.setdefault(ticker, today)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:   # noqa: BLE001 - an unwritable store must not break the briefing
        pass
    return [{**p, "entry_date": p.get("entry_date") or seen.get(p["ticker"], "")}
            for p in holdings]


def resolve_positions(*, configured=is_configured, fetch=fetch_holdings,
                      load_positions=config.load_positions,
                      load_overrides=config.load_position_overrides,
                      fetch_entry_dates=fetch_entry_dates,
                      on_error=None, data_dir=None, today=None) -> list:
    """The holdings source for the briefing.

    SnapTrade when configured (merging optional per-ticker overrides from positions.yaml);
    otherwise the positions.yaml file. If a live sync errors, fall back to positions.yaml
    so the daily briefing never breaks on a SnapTrade outage.

    entry_date precedence, highest first:
      1. positions.yaml `entry_date:`      — an explicit manual pin, always wins
      2. brokerage activity feed           — the TRUE position-open date (fetch_entry_dates)
      3. data/position_first_seen.json     — when activity history doesn't reach back far enough
      4. today's stamp                     — a position seen for the first time right now

    Layer 2 matters because layer 3 only knows when the APP first noticed a holding, which for
    anything bought before the store existed is just the day the store was created. A wrong
    entry_date silently suppresses exits: QURE pinned to an ADD date (2026-06-17) rather than
    its real open (2025-12-05) hid a 234-day time_exit. `data_dir` enables layers 2-4.
    """
    if not configured():
        return load_positions()
    try:
        live = fetch()
    except Exception as e:   # noqa: BLE001 - any sync failure must degrade gracefully
        if on_error is not None:
            on_error(e)
        return load_positions()
    if data_dir is not None:
        derived = {}
        try:
            derived = fetch_entry_dates() or {}
        except Exception as e:   # noqa: BLE001 - fall through to first-seen, never fabricate
            if on_error is not None:
                on_error(e)
        live = [{**p, "entry_date": p.get("entry_date") or derived.get(p["ticker"], "")}
                for p in live]
        live = _stamp_first_seen(live, data_dir, today or date.today().isoformat())
    overrides = load_overrides()
    return [{**p, **overrides.get(p["ticker"], {})} for p in live]
