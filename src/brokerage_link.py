"""Connect a brokerage (Robinhood) to Stock Advisor via SnapTrade — the lifecycle seam.

The UI and routes call ONLY the four lifecycle functions here (save_keys, start_connect,
check_connection, disconnect) plus the two cheap status helpers (keys_present, is_linked).
Today these talk to SnapTrade directly using the user's own (BYO) app keys. A future SaaS
build implements the same surface against a hosted backend that holds the consumer key —
the routes and UI never change. See the spec for the upgrade path.

Read-only: this module establishes the link and reads account presence; it never trades.
"""
from __future__ import annotations

from src import config, secrets_store

USER_ID_DEFAULT = "stock-advisor"


class BrokerageError(Exception):
    """A user-facing brokerage-link failure (bad keys, portal unavailable, etc.)."""


def _client(client_id, consumer_key):
    from snaptrade_client import SnapTrade
    return SnapTrade(consumer_key=consumer_key, client_id=client_id)


def _field(body, *names):
    """Read a field from an SDK response body that may be a dict, frozendict, or object."""
    for name in names:
        try:
            if name in body:
                return body[name]
        except TypeError:
            pass
        if hasattr(body, name):
            return getattr(body, name)
    return None


def _creds(config_dir):
    ic = config.load_integrations(config_dir)
    return (
        ic.get("SNAPTRADE_CLIENT_ID"),
        secrets_store.get_secret("SNAPTRADE_CONSUMER_KEY"),
        ic.get("SNAPTRADE_USER_ID"),
        secrets_store.get_secret("SNAPTRADE_USER_SECRET"),
    )


def keys_present(config_dir) -> bool:
    """True when both app keys (client id + consumer key) are stored."""
    client_id = config.load_integrations(config_dir).get("SNAPTRADE_CLIENT_ID")
    return bool(client_id) and secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY")


def is_linked(config_dir) -> bool:
    """True when a connected user has been registered (user id + secret stored)."""
    user_id = config.load_integrations(config_dir).get("SNAPTRADE_USER_ID")
    return bool(user_id) and secrets_store.has_secret("SNAPTRADE_USER_SECRET")


def save_keys(config_dir, client_id, consumer_key) -> None:
    """Persist the user's SnapTrade app keys (client id -> config, consumer key -> keyring)."""
    config.save_brokerage_identity(config_dir, client_id=(client_id or "").strip())
    ck = (consumer_key or "").strip()
    if ck:
        secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", ck)
    else:
        secrets_store.delete_secret("SNAPTRADE_CONSUMER_KEY")


def start_connect(config_dir, *, client_factory=_client) -> str:
    """Register the connected user (once) and return the SnapTrade portal URL to open."""
    client_id, consumer_key, user_id, user_secret = _creds(config_dir)
    if not client_id or not consumer_key:
        raise BrokerageError("Enter your SnapTrade Client ID and Consumer Key first.")
    client = client_factory(client_id, consumer_key)

    if not user_id or not user_secret:
        user_id = user_id or USER_ID_DEFAULT
        try:
            resp = client.authentication.register_snap_trade_user(user_id=user_id)
            user_secret = _field(resp.body, "userSecret", "user_secret")
        except Exception as e:   # noqa: BLE001 - surface a friendly message, not the SDK trace
            raise BrokerageError(
                "Could not register with SnapTrade — double-check your keys. "
                "Note the free tier allows 5 connections."
            ) from e
        if not user_secret:
            raise BrokerageError("Registration returned no user secret — check your keys.")
        config.save_brokerage_identity(config_dir, user_id=user_id)
        secrets_store.set_secret("SNAPTRADE_USER_SECRET", user_secret)

    try:
        resp = client.authentication.login_snap_trade_user(user_id=user_id, user_secret=user_secret)
        url = _field(resp.body, "redirectURI", "redirect_uri")
    except Exception as e:   # noqa: BLE001
        raise BrokerageError("Could not open the SnapTrade portal — try again in a moment.") from e
    if not url:
        raise BrokerageError("Could not open the SnapTrade portal — try again in a moment.")
    return url


def check_connection(config_dir, *, client_factory=_client) -> dict:
    """Poll SnapTrade for linked accounts. Returns {connected, account_count}.

    Raises BrokerageError on a transport/credential failure so the route can return 502;
    'no accounts yet' is NOT an error — it returns connected=False.
    """
    client_id, consumer_key, user_id, user_secret = _creds(config_dir)
    if not all([client_id, consumer_key, user_id, user_secret]):
        return {"connected": False, "account_count": 0}
    client = client_factory(client_id, consumer_key)
    try:
        resp = client.account_information.list_user_accounts(
            user_id=user_id, user_secret=user_secret)
        accounts = list(resp.body) if resp.body else []
    except Exception as e:   # noqa: BLE001
        raise BrokerageError("Couldn't reach SnapTrade — finish in the browser, then retry.") from e
    return {"connected": len(accounts) > 0, "account_count": len(accounts)}


def disconnect(config_dir) -> None:
    """Clear all stored brokerage credentials (both secrets and both identifiers)."""
    config.save_brokerage_identity(config_dir, client_id="", user_id="")
    secrets_store.delete_secret("SNAPTRADE_CONSUMER_KEY")
    secrets_store.delete_secret("SNAPTRADE_USER_SECRET")
