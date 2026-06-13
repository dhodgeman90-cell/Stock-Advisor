import datetime as dt

from src import congress


# --- amount range parsing -------------------------------------------------
def test_parse_amount_range():
    assert congress._parse_amount("$1,001 - $15,000") == (1001.0, 15000.0)


def test_parse_amount_single_value():
    assert congress._parse_amount("$50,000") == (50000.0, 50000.0)


def test_parse_amount_unparseable_is_zero():
    assert congress._parse_amount("") == (0.0, 0.0)
    assert congress._parse_amount(None) == (0.0, 0.0)


# --- record normalization (House + Senate shapes) -------------------------
HOUSE = [
    {"ticker": "aapl", "representative": "Hon. Jane Doe", "type": "purchase",
     "amount": "$1,001 - $15,000", "transaction_date": "2026-05-28",
     "disclosure_date": "2026-06-01"},
    {"ticker": "TSLA", "representative": "Hon. John Roe", "type": "sale_full",
     "amount": "$15,001 - $50,000", "transaction_date": "2026-05-20",
     "disclosure_date": "06/05/2026"},
    {"ticker": "--", "representative": "Hon. Nobody", "type": "purchase",
     "amount": "$1,001 - $15,000", "transaction_date": "x", "disclosure_date": "x"},
]


def test_parse_congress_normalizes_side_and_amount():
    out = congress._parse_congress(HOUSE, chamber="house")
    by_ticker = {t["ticker"]: t for t in out}
    assert "AAPL" in by_ticker and "TSLA" in by_ticker
    assert "--" not in by_ticker            # junk ticker dropped
    assert by_ticker["AAPL"]["side"] == "buy"
    assert by_ticker["TSLA"]["side"] == "sell"      # sale_full -> sell
    assert by_ticker["AAPL"]["amount_low"] == 1001.0
    assert by_ticker["AAPL"]["chamber"] == "house"
    assert by_ticker["AAPL"]["member"] == "Hon. Jane Doe"


def test_parse_congress_reads_fmp_shape():
    # Financial Modeling Prep uses symbol / transactionType / disclosureDate and a
    # split first/last name instead of the StockWatcher field names.
    fmp = [{"symbol": "MSFT", "firstName": "Jane", "lastName": "Doe",
            "office": "Doe, Jane (Senator)", "type": "Purchase",
            "amount": "$15,001 - $50,000", "transactionDate": "2026-05-30",
            "disclosureDate": "2026-06-02"}]
    out = congress._parse_congress(fmp, chamber="senate")
    assert out[0]["ticker"] == "MSFT"
    assert out[0]["side"] == "buy"
    assert out[0]["member"] == "Jane Doe"
    assert out[0]["disclosure_date"] == "2026-06-02"


def test_parse_congress_reads_senate_member_field():
    senate = [{"ticker": "NVDA", "senator": "Sen. Sam Smith", "type": "purchase",
               "amount": "$50,001 - $100,000", "transaction_date": "2026-05-30",
               "disclosure_date": "2026-06-02"}]
    out = congress._parse_congress(senate, chamber="senate")
    assert out[0]["member"] == "Sen. Sam Smith"
    assert out[0]["chamber"] == "senate"


# --- aggregation by ticker ------------------------------------------------
def _trade(ticker, member, side, low, high, disclosure):
    return {"ticker": ticker, "member": member, "chamber": "house", "side": side,
            "amount_low": low, "amount_high": high, "transaction_date": disclosure,
            "disclosure_date": disclosure}


def test_aggregate_by_ticker_nets_dollars_and_counts_members():
    trades = [
        _trade("AAPL", "X", "buy", 1001, 15000, "2026-06-01"),
        _trade("AAPL", "Y", "buy", 15001, 50000, "2026-06-10"),
        _trade("AAPL", "X", "sell", 1001, 15000, "2026-05-01"),
    ]
    agg = congress.aggregate_by_ticker(trades)["AAPL"]
    assert agg["n_buys"] == 2
    assert agg["n_sells"] == 1
    assert agg["n_members"] == 2
    assert agg["net_side"] == "buy"                 # buy dollars dominate
    assert agg["most_recent_disclosure"] == "2026-06-10"


def test_aggregate_net_side_sell_when_sells_dominate():
    trades = [
        _trade("XYZ", "A", "buy", 1001, 15000, "2026-06-01"),
        _trade("XYZ", "B", "sell", 100001, 250000, "2026-06-02"),
    ]
    assert congress.aggregate_by_ticker(trades)["XYZ"]["net_side"] == "sell"


# --- recent large trades (discovery feed) ---------------------------------
def test_recent_large_trades_filters_by_size_and_recency():
    today = dt.date(2026, 6, 12)
    trades = [
        _trade("BIG", "A", "buy", 100001, 250000, "2026-06-10"),   # large + recent
        _trade("SMALL", "B", "buy", 1001, 15000, "2026-06-10"),    # too small
        _trade("OLD", "C", "buy", 100001, 250000, "2026-01-01"),   # too old
    ]
    out = congress.recent_large_trades(trades, min_amount=50000, lookback_days=30, today=today)
    tickers = {t["ticker"] for t in out}
    assert tickers == {"BIG"}


# --- networked fetch with cache fallback (DI) -----------------------------
def test_get_congress_trades_caches_and_falls_back(tmp_path):
    cache = tmp_path / "congress.json"
    payload = {"house": HOUSE, "senate": []}
    out = congress.get_congress_trades(fetch=lambda: payload, cache_path=cache)
    assert any(t["ticker"] == "AAPL" for t in out)
    assert cache.exists()

    def boom():
        raise RuntimeError("network down")

    out2 = congress.get_congress_trades(fetch=boom, cache_path=cache)
    assert any(t["ticker"] == "AAPL" for t in out2)     # served from cache


def test_get_congress_trades_no_cache_no_network_is_empty(tmp_path):
    def boom():
        raise RuntimeError("down")

    assert congress.get_congress_trades(fetch=boom, cache_path=tmp_path / "x.json") == []
