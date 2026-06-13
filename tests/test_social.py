from src import social


SAMPLE = {
    "results": [
        {"rank": 1, "ticker": "gme", "name": "GameStop",
         "mentions": 120, "upvotes": 4000, "rank_24h_ago": 4, "mentions_24h_ago": 80},
        {"rank": 2, "ticker": "AAPL", "name": "Apple",
         "mentions": 50, "upvotes": 900, "rank_24h_ago": 2, "mentions_24h_ago": 70},
        {"rank": 3, "ticker": "", "name": "blank",
         "mentions": 10, "upvotes": 5},
    ],
    "count": 3,
}


def test_parse_apewisdom_keys_by_uppercase_ticker():
    out = social._parse_apewisdom(SAMPLE)
    assert set(out) == {"GME", "AAPL"}          # blank ticker dropped, lowercased uppercased


def test_parse_apewisdom_computes_mention_and_rank_change():
    out = social._parse_apewisdom(SAMPLE)
    assert out["GME"]["mentions"] == 120
    assert out["GME"]["mentions_change"] == 40   # 120 - 80
    assert out["GME"]["rank_change"] == 3        # climbed from rank 4 to 1
    # AAPL is cooling: fewer mentions, rank slipped
    assert out["AAPL"]["mentions_change"] == -20
    assert out["AAPL"]["rank_change"] == 0       # 2 -> 2


def test_parse_apewisdom_missing_prior_fields_are_none():
    out = social._parse_apewisdom({"results": [
        {"rank": 1, "ticker": "TSLA", "mentions": 30, "upvotes": 100},
    ]})
    assert out["TSLA"]["mentions_change"] is None
    assert out["TSLA"]["rank_change"] is None


def test_parse_apewisdom_empty_payload():
    assert social._parse_apewisdom({}) == {}


def test_get_wsb_sentiment_parses_and_writes_cache(tmp_path):
    cache = tmp_path / "wsb.json"
    out = social.get_wsb_sentiment(fetch=lambda: SAMPLE, cache_path=cache)
    assert set(out) == {"GME", "AAPL"}
    assert cache.exists()           # successful fetch is persisted for fallback


def test_get_wsb_sentiment_falls_back_to_cache_on_fetch_error(tmp_path):
    cache = tmp_path / "wsb.json"
    social.get_wsb_sentiment(fetch=lambda: SAMPLE, cache_path=cache)   # seed cache

    def boom():
        raise RuntimeError("network down")

    out = social.get_wsb_sentiment(fetch=boom, cache_path=cache)
    assert out["GME"]["mentions"] == 120          # served from cache


def test_get_wsb_sentiment_no_cache_and_no_network_is_empty(tmp_path):
    def boom():
        raise RuntimeError("network down")

    out = social.get_wsb_sentiment(fetch=boom, cache_path=tmp_path / "missing.json")
    assert out == {}
