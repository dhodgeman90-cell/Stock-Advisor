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


# ---- entry_date stamping -------------------------------------------------
# SnapTrade positions carry no purchase date, and a blank entry_date silently disables
# BOTH the trailing stop (peak collapses to entry, so `price <= peak*(1-trail)` can never
# fire on a winner) and the live time-stop. These lock that shut.

def _live(*tickers):
    return [{"ticker": t, "entry_price": 100.0, "shares": 1, "entry_date": "",
             "stop_loss_pct": None, "take_profit_pct": None, "trailing_stop_pct": None}
            for t in tickers]


def test_resolve_positions_never_returns_a_blank_entry_date(tmp_path):
    out = broker.resolve_positions(
        configured=lambda: True, fetch=lambda: _live("NVDA", "AAPL"),
        data_dir=tmp_path, today="2026-07-27",
    )
    assert [p["ticker"] for p in out] == ["NVDA", "AAPL"]
    assert all(p["entry_date"] for p in out), "a blank entry_date disables the trailing stop"
    assert all(p["entry_date"] == "2026-07-27" for p in out)


def test_first_seen_date_is_sticky_across_syncs(tmp_path):
    broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"),
                             data_dir=tmp_path, today="2026-07-01")
    out = broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"),
                                   data_dir=tmp_path, today="2026-07-27")
    assert out[0]["entry_date"] == "2026-07-01"   # not re-stamped to today


def test_closed_position_is_pruned_so_a_rebuy_restarts_the_clock(tmp_path):
    broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"),
                             data_dir=tmp_path, today="2026-07-01")
    broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("AAPL"),
                             data_dir=tmp_path, today="2026-07-10")     # NVDA sold
    out = broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"),
                                   data_dir=tmp_path, today="2026-07-27")
    assert out[0]["entry_date"] == "2026-07-27"   # re-bought -> fresh clock, not 2026-07-01


def test_positions_yaml_entry_date_override_beats_first_seen(tmp_path):
    out = broker.resolve_positions(
        configured=lambda: True, fetch=lambda: _live("NVDA"),
        load_overrides=lambda: {"NVDA": {"entry_date": "2026-01-15"}},
        data_dir=tmp_path, today="2026-07-27",
    )
    assert out[0]["entry_date"] == "2026-01-15"   # you know the real date; we defer to it


def test_entry_date_stamping_is_skipped_without_a_data_dir():
    out = broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"))
    assert out[0]["entry_date"] == ""   # no store to write to -> unchanged, never crashes


def test_unreadable_first_seen_store_does_not_break_the_sync(tmp_path):
    (tmp_path / "position_first_seen.json").write_text("{ not json", encoding="utf-8")
    out = broker.resolve_positions(configured=lambda: True, fetch=lambda: _live("NVDA"),
                                   data_dir=tmp_path, today="2026-07-27")
    assert out[0]["entry_date"] == "2026-07-27"   # corrupt store is rebuilt, not fatal
