import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "wsb_sentiment.json"

# ApeWisdom aggregates r/wallstreetbets mentions for free with no API key.
APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"


# ApeWisdom is Cloudflare-fronted and 403s the default Python-urllib agent.
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAdvisor/1.0"


def _default_fetch() -> dict:
    """Fetch the raw ApeWisdom WSB payload. Network call — not unit-tested."""
    import urllib.request
    req = urllib.request.Request(APEWISDOM_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_wsb_sentiment(fetch=_default_fetch, cache_path=CACHE_PATH) -> dict:
    """Return {TICKER: signal} from r/wallstreetbets buzz.

    On a successful fetch the raw payload is cached so a later outage degrades
    gracefully to the last good snapshot (mirrors data.py's cache fallback). When
    neither the network nor a cache is available, returns {} (no opinion).
    """
    cache_path = Path(cache_path)
    try:
        payload = fetch()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return _parse_apewisdom(payload)
    except Exception:
        if cache_path.exists():
            try:
                return _parse_apewisdom(json.loads(cache_path.read_text(encoding="utf-8")))
            except Exception:
                return {}
        return {}


def _parse_apewisdom(payload: dict) -> dict:
    """Normalize an ApeWisdom WSB response into {TICKER: signal} (pure, testable).

    ApeWisdom's free endpoint returns per-ticker mention counts, upvotes, and the
    rank/mentions from 24h ago. We key by upper-cased ticker and derive the daily
    deltas (mention surge and rank climb) that drive the social signal downstream.
    """
    out = {}
    for r in payload.get("results", []):
        ticker = str(r.get("ticker") or "").upper()
        if not ticker:
            continue
        mentions = int(r.get("mentions") or 0)
        rank = r.get("rank")
        rank = int(rank) if rank is not None else None
        mentions_prev = r.get("mentions_24h_ago")
        mentions_prev = int(mentions_prev) if mentions_prev is not None else None
        rank_prev = r.get("rank_24h_ago")
        rank_prev = int(rank_prev) if rank_prev is not None else None
        out[ticker] = {
            "rank": rank,
            "mentions": mentions,
            "upvotes": int(r.get("upvotes") or 0),
            "mentions_24h_ago": mentions_prev,
            "mentions_change": (mentions - mentions_prev) if mentions_prev is not None else None,
            # rank climbing toward #1 is positive: prev_rank - rank
            "rank_change": (rank_prev - rank) if (rank_prev is not None and rank is not None) else None,
        }
    return out
