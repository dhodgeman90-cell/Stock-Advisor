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
import os

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


def _default_list_positions(client, account_id) -> list:
    # get_user_holdings replaces the deprecated get_user_account_positions; its body is a
    # holdings object whose `positions` array has the same per-position shape we parse.
    resp = client.account_information.get_user_holdings(
        user_id=os.environ["SNAPTRADE_USER_ID"],
        user_secret=os.environ["SNAPTRADE_USER_SECRET"],
        account_id=account_id,
    )
    body = resp.body or {}
    positions = body["positions"] if "positions" in body else []
    return list(positions)


# ---- pure parsing/aggregation (fully unit-tested) ----

def _extract_ticker(pos: dict):
    """Ticker string from a SnapTrade position: documented path symbol.symbol.symbol."""
    symbol = pos.get("symbol") or {}
    universal = symbol.get("symbol") or {}
    ticker = universal.get("symbol") or universal.get("raw_symbol") or symbol.get("raw_symbol")
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


def resolve_positions(*, configured=is_configured, fetch=fetch_holdings,
                      load_positions=config.load_positions,
                      load_overrides=config.load_position_overrides,
                      on_error=None) -> list:
    """The holdings source for the briefing.

    SnapTrade when configured (merging optional per-ticker overrides from positions.yaml);
    otherwise the positions.yaml file. If a live sync errors, fall back to positions.yaml
    so the daily briefing never breaks on a SnapTrade outage.
    """
    if not configured():
        return load_positions()
    try:
        live = fetch()
    except Exception as e:   # noqa: BLE001 - any sync failure must degrade gracefully
        if on_error is not None:
            on_error(e)
        return load_positions()
    overrides = load_overrides()
    return [{**p, **overrides.get(p["ticker"], {})} for p in live]
