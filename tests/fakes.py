class FakeClient:
    """LLM client stand-in that returns a fixed reply string."""

    def __init__(self, reply: str):
        self.reply = reply

    def complete(self, system: str, user: str) -> str:
        return self.reply


class BoomClient:
    """LLM client stand-in that always raises (simulates an outage/bad key)."""

    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("boom")


class _Resp:
    """Stand-in for the SnapTrade SDK's ApiResponse: exposes parsed JSON via .body."""

    def __init__(self, body):
        self.body = body


class _FakeAccountInfo:
    def __init__(self, accounts, positions_by_account):
        self._accounts = accounts
        self._positions_by_account = positions_by_account
        self.positions_calls = []   # account_ids queried, in order

    def list_user_accounts(self, user_id=None, user_secret=None):
        return _Resp(list(self._accounts))

    def get_user_account_positions(self, user_id=None, user_secret=None, account_id=None):
        self.positions_calls.append(account_id)
        return _Resp(list(self._positions_by_account.get(account_id, [])))


class FakeSnapTrade:
    """Minimal SnapTrade SDK stand-in serving canned accounts + positions."""

    def __init__(self, accounts, positions_by_account):
        self.account_information = _FakeAccountInfo(accounts, positions_by_account)


def snaptrade_position(ticker, units, average_purchase_price, price=None):
    """A raw SnapTrade position dict with the real nesting (ticker at symbol.symbol.symbol)."""
    return {
        "symbol": {"symbol": {"symbol": ticker, "raw_symbol": ticker}},
        "units": units,
        "average_purchase_price": average_purchase_price,
        "price": average_purchase_price if price is None else price,
    }


class FakeSMTP:
    """SMTP stand-in usable as a context manager; records login + sent message."""

    def __init__(self):
        self.logged_in = None
        self.sent_message = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent_message = msg


class FakeKeyring:
    """In-memory stand-in for the `keyring` module's password API.

    Used by the autouse conftest fixture so tests never touch the real OS
    credential store. Mirrors keyring's interface: set/get/delete_password,
    keyed by (service, key). delete of a missing key raises, like keyring does.
    """

    def __init__(self):
        self._store = {}

    def get_password(self, service, key):
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self._store[(service, key)] = value

    def delete_password(self, service, key):
        if (service, key) not in self._store:
            raise KeyError(f"no such password: {service}/{key}")
        del self._store[(service, key)]
