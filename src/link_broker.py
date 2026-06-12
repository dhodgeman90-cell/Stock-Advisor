"""One-time setup: connect your Robinhood account to Stock Advisor via SnapTrade.

    python -m src.link_broker

You only run this once. It registers you with SnapTrade, opens a browser so you can
log into Robinhood and authorize the connection, then verifies it can read your holdings.
After that, every daily briefing syncs your holdings automatically — no password stored
locally, no 2FA prompt on the scheduled run.
"""
import os
import sys
import webbrowser
from pathlib import Path

from src import broker

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


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


def main() -> int:
    _load_env()

    client_id = os.environ.get("SNAPTRADE_CLIENT_ID")
    consumer_key = os.environ.get("SNAPTRADE_CONSUMER_KEY")
    if not client_id or not consumer_key:
        print(
            "Missing SnapTrade app keys.\n"
            "  1) Create a free account at https://snaptrade.com and create an app.\n"
            "  2) Add these to your .env, then re-run `python -m src.link_broker`:\n"
            "       SNAPTRADE_CLIENT_ID=...\n"
            "       SNAPTRADE_CONSUMER_KEY=..."
        )
        return 1

    from snaptrade_client import SnapTrade
    client = SnapTrade(consumer_key=consumer_key, client_id=client_id)

    user_id = os.environ.get("SNAPTRADE_USER_ID") or "stock-advisor"
    os.environ["SNAPTRADE_USER_ID"] = user_id
    user_secret = os.environ.get("SNAPTRADE_USER_SECRET")

    if not user_secret:
        print(f"Registering SnapTrade user '{user_id}' ...")
        try:
            resp = client.authentication.register_snap_trade_user(user_id=user_id)
            user_secret = _field(resp.body, "userSecret", "user_secret")
        except Exception as e:   # noqa: BLE001
            print(
                f"Could not register user: {e}\n"
                "If this user already exists but you lost the secret, reset it in the "
                "SnapTrade dashboard (or delete the user) and re-run."
            )
            return 1
        if not user_secret:
            print(f"Registration returned no userSecret: {resp.body}")
            return 1
        print("\n=== SAVE THIS NOW — paste into your .env (shown only once) ===")
        print(f"SNAPTRADE_USER_ID={user_id}")
        print(f"SNAPTRADE_USER_SECRET={user_secret}")
        print("=============================================================\n")

    os.environ["SNAPTRADE_USER_SECRET"] = user_secret

    print("Opening the SnapTrade connection portal in your browser ...")
    resp = client.authentication.login_snap_trade_user(user_id=user_id, user_secret=user_secret)
    redirect = _field(resp.body, "redirectURI", "redirect_uri")
    if not redirect:
        print(f"Unexpected login response (no redirect URL): {resp.body}")
        return 1
    print(f"If it doesn't open automatically, paste this into your browser:\n  {redirect}\n")
    try:
        webbrowser.open(redirect)
    except Exception:
        pass

    input("After you finish logging into Robinhood and approving access, press Enter to verify ... ")

    try:
        accounts = broker._default_list_accounts(client)
    except Exception as e:   # noqa: BLE001
        print(f"Could not list accounts yet: {e}\nWait a few seconds, then re-run to verify.")
        return 1
    if not accounts:
        print("No connected accounts found yet. If you just authorized, wait a moment and re-run.")
        return 1

    print(f"Connected {len(accounts)} account(s).")
    try:
        holdings = broker.fetch_holdings(client_factory=lambda: client)
        names = ", ".join(h["ticker"] for h in holdings) or "(none yet)"
        print(f"Detected {len(holdings)} holding(s): {names}")
    except Exception as e:   # noqa: BLE001
        print(f"(Connected, but could not read holdings yet: {e})")

    print("\nDone. Future briefings will sync your holdings automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
