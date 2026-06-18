import pytest

from src import brokerage_link, config, secrets_store
from tests.fakes import FakeSnapTrade


def test_save_keys_persists_client_id_and_consumer_key(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    assert config.load_integrations(tmp_path)["SNAPTRADE_CLIENT_ID"] == "cid-1"
    assert secrets_store.get_secret("SNAPTRADE_CONSUMER_KEY") == "ckey-1"
    assert brokerage_link.keys_present(tmp_path) is True


def test_save_keys_blank_consumer_key_clears_it(tmp_path):
    secrets_store.set_secret("SNAPTRADE_CONSUMER_KEY", "old")
    brokerage_link.save_keys(tmp_path, "cid-1", "")
    assert secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY") is False


def test_start_connect_requires_keys(tmp_path):
    with pytest.raises(brokerage_link.BrokerageError):
        brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: FakeSnapTrade())


def test_start_connect_registers_user_then_returns_portal_url(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    fake = FakeSnapTrade(user_secret="us-xyz", redirect_uri="https://portal.example/abc")
    url = brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: fake)
    assert url == "https://portal.example/abc"
    assert fake.authentication.registered == ["stock-advisor"]      # registered once
    assert config.load_integrations(tmp_path)["SNAPTRADE_USER_ID"] == "stock-advisor"
    assert secrets_store.get_secret("SNAPTRADE_USER_SECRET") == "us-xyz"


def test_start_connect_reuses_existing_user_without_reregistering(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="existing-user")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "existing-secret")
    fake = FakeSnapTrade(redirect_uri="https://portal.example/reuse")
    url = brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: fake)
    assert url == "https://portal.example/reuse"
    assert fake.authentication.registered == []                    # no re-registration


def test_check_connection_reports_account_count(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    fake = FakeSnapTrade(accounts=[{"id": "a"}, {"id": "b"}])
    status = brokerage_link.check_connection(tmp_path, client_factory=lambda c, k: fake)
    assert status == {"connected": True, "account_count": 2}


def test_check_connection_false_when_not_linked(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")   # keys but never connected
    status = brokerage_link.check_connection(tmp_path, client_factory=lambda c, k: FakeSnapTrade())
    assert status == {"connected": False, "account_count": 0}


def test_is_linked_true_only_after_connect(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    assert brokerage_link.is_linked(tmp_path) is False
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    assert brokerage_link.is_linked(tmp_path) is True


def test_disconnect_clears_everything(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")
    config.save_brokerage_identity(tmp_path, user_id="u")
    secrets_store.set_secret("SNAPTRADE_USER_SECRET", "s")
    brokerage_link.disconnect(tmp_path)
    ic = config.load_integrations(tmp_path)
    assert "SNAPTRADE_CLIENT_ID" not in ic and "SNAPTRADE_USER_ID" not in ic
    assert secrets_store.has_secret("SNAPTRADE_CONSUMER_KEY") is False
    assert secrets_store.has_secret("SNAPTRADE_USER_SECRET") is False


def test_start_connect_maps_sdk_error_to_brokerage_error(tmp_path):
    brokerage_link.save_keys(tmp_path, "cid-1", "ckey-1")

    class Boom(FakeSnapTrade):
        def __init__(self):
            super().__init__()
            class _A:
                def register_snap_trade_user(self, user_id=None):
                    raise RuntimeError("401 unauthorized")
            self.authentication = _A()

    with pytest.raises(brokerage_link.BrokerageError):
        brokerage_link.start_connect(tmp_path, client_factory=lambda c, k: Boom())
