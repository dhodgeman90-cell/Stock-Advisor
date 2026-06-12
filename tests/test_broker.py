import pytest

from src import broker
from tests.fakes import FakeSnapTrade, snaptrade_position


def _set_link_env(monkeypatch):
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "cid")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "ckey")
    monkeypatch.setenv("SNAPTRADE_USER_ID", "stock-advisor")
    monkeypatch.setenv("SNAPTRADE_USER_SECRET", "secret")


# ---- is_configured -------------------------------------------------------

def test_is_configured_true_only_when_all_env_present(monkeypatch):
    for k in ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
              "SNAPTRADE_USER_ID", "SNAPTRADE_USER_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert broker.is_configured() is False
    _set_link_env(monkeypatch)
    assert broker.is_configured() is True
    monkeypatch.delenv("SNAPTRADE_USER_SECRET")
    assert broker.is_configured() is False   # one missing -> not configured


# ---- fetch_holdings ------------------------------------------------------

def test_fetch_holdings_parses_ticker_units_and_cost_basis(monkeypatch):
    _set_link_env(monkeypatch)
    fake = FakeSnapTrade(
        accounts=[{"id": "acct-1"}],
        positions_by_account={"acct-1": [
            snaptrade_position("AAPL", 3, 140.0),
            snaptrade_position("tsla", 0.5, 300.0),   # lower-case -> upper-cased
        ]},
    )
    holdings = {h["ticker"]: h for h in broker.fetch_holdings(client_factory=lambda: fake)}
    assert holdings["AAPL"]["shares"] == 3
    assert holdings["AAPL"]["entry_price"] == 140.0
    assert holdings["TSLA"]["shares"] == 0.5
    assert holdings["TSLA"]["entry_price"] == 300.0
    # shape matches config.load_positions() output so downstream code is unchanged
    assert holdings["AAPL"]["stop_loss_pct"] is None
    assert holdings["AAPL"]["entry_date"] == ""


def test_fetch_holdings_aggregates_same_ticker_across_accounts_share_weighted(monkeypatch):
    _set_link_env(monkeypatch)
    fake = FakeSnapTrade(
        accounts=[{"id": "a"}, {"id": "b"}],
        positions_by_account={
            "a": [snaptrade_position("MSFT", 2, 100.0)],   # 2 sh @ 100
            "b": [snaptrade_position("MSFT", 3, 200.0)],   # 3 sh @ 200
        },
    )
    holdings = {h["ticker"]: h for h in broker.fetch_holdings(client_factory=lambda: fake)}
    assert holdings["MSFT"]["shares"] == 5
    # share-weighted cost = (2*100 + 3*200) / 5 = 160
    assert holdings["MSFT"]["entry_price"] == pytest.approx(160.0)


def test_fetch_holdings_skips_zero_units_and_unparseable(monkeypatch):
    _set_link_env(monkeypatch)
    bad = {"symbol": {"symbol": {}}, "units": None, "average_purchase_price": None}
    fake = FakeSnapTrade(
        accounts=[{"id": "a"}],
        positions_by_account={"a": [
            snaptrade_position("GOOD", 1, 10.0),
            snaptrade_position("ZERO", 0, 50.0),   # zero units -> skipped
            bad,                                    # missing fields -> skipped
        ]},
    )
    tickers = {h["ticker"] for h in broker.fetch_holdings(client_factory=lambda: fake)}
    assert tickers == {"GOOD"}


def test_fetch_holdings_uses_single_account_env_without_listing(monkeypatch):
    _set_link_env(monkeypatch)
    monkeypatch.setenv("SNAPTRADE_ACCOUNT_ID", "acct-9")
    fake = FakeSnapTrade(
        accounts=[{"id": "should-not-be-used"}],
        positions_by_account={"acct-9": [snaptrade_position("NVDA", 4, 120.0)]},
    )
    holdings = broker.fetch_holdings(client_factory=lambda: fake)
    assert [h["ticker"] for h in holdings] == ["NVDA"]
    # only the pinned account was queried; account listing was skipped
    assert fake.account_information.positions_calls == ["acct-9"]


# ---- resolve_positions (orchestration + fallback) ------------------------

def test_resolve_positions_uses_yaml_when_not_configured():
    sentinel = [{"ticker": "YAML"}]
    out = broker.resolve_positions(
        configured=lambda: False,
        load_positions=lambda: sentinel,
    )
    assert out is sentinel


def test_resolve_positions_falls_back_to_yaml_on_fetch_error():
    errors = []

    def boom():
        raise RuntimeError("snaptrade down")

    out = broker.resolve_positions(
        configured=lambda: True,
        fetch=boom,
        load_positions=lambda: [{"ticker": "FALLBACK"}],
        on_error=errors.append,
    )
    assert out == [{"ticker": "FALLBACK"}]
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)


def test_resolve_positions_merges_overrides_by_ticker():
    live = [
        {"ticker": "NVDA", "entry_price": 120.0, "shares": 2,
         "stop_loss_pct": None, "take_profit_pct": None},
        {"ticker": "AAPL", "entry_price": 200.0, "shares": 1,
         "stop_loss_pct": None, "take_profit_pct": None},
    ]
    out = {p["ticker"]: p for p in broker.resolve_positions(
        configured=lambda: True,
        fetch=lambda: live,
        load_overrides=lambda: {"NVDA": {"stop_loss_pct": 10, "take_profit_pct": 25}},
    )}
    assert out["NVDA"]["stop_loss_pct"] == 10          # override applied
    assert out["NVDA"]["take_profit_pct"] == 25
    assert out["NVDA"]["entry_price"] == 120.0          # live value preserved
    assert out["AAPL"]["stop_loss_pct"] is None         # no override -> untouched
