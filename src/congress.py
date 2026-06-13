"""Congressional trading disclosures.

By the STOCK Act these filings are disclosed with up to a ~45-day legal delay, so this
is NOT a real-time feed: the value is reacting fast to *newly disclosed* large trades.
Signals are keyed on disclosure date and weighted heavily downstream, but labeled with
their lag in the briefing so the owner reads them honestly.

Default free source: the public House/Senate Stock Watcher JSON datasets (no API key).
A paid key (FMP/Quiver) can later replace `_default_fetch` without touching parsing.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "congress_trades.json"

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

_BUY_TYPES = {"purchase", "buy"}
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")
_NUM = re.compile(r"[\d,]+(?:\.\d+)?")


def is_configured() -> bool:
    """True when a paid congressional-data key is present (optional upgrade path)."""
    return bool(os.environ.get("FMP_API_KEY"))


def _parse_amount(text):
    """Parse a disclosure amount range like '$1,001 - $15,000' into (low, high) floats."""
    if not text:
        return (0.0, 0.0)
    nums = [float(m.group().replace(",", "")) for m in _NUM.finditer(str(text))]
    if not nums:
        return (0.0, 0.0)
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (nums[0], nums[1])


def _parse_date(text):
    """Lenient date parse across the formats the watcher datasets use; None on failure."""
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(str(text), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _clean_ticker(raw):
    ticker = str(raw or "").strip().upper()
    if not ticker or not ticker.isalpha():     # drop "--", "", "N/A", option strings
        return None
    return ticker


def _field(record, *keys):
    """First present, non-empty value among aliases (handles StockWatcher + FMP shapes)."""
    for k in keys:
        v = record.get(k)
        if v:
            return v
    return None


def _member_name(r):
    name = _field(r, "representative", "senator", "member")
    if name:
        return name
    first, last = r.get("firstName"), r.get("lastName")
    if first or last:
        return f"{first or ''} {last or ''}".strip()
    return r.get("office") or ""


def _parse_congress(records, chamber="house"):
    """Normalize raw disclosure records into a flat list of trades.

    Tolerates both the StockWatcher field names (ticker / type / disclosure_date) and
    the Financial Modeling Prep names (symbol / transactionType / disclosureDate), so a
    free FMP key can drive the feed without touching downstream code.
    """
    out = []
    for r in records:
        ticker = _clean_ticker(_field(r, "ticker", "symbol"))
        if not ticker:
            continue
        ttype = str(_field(r, "type", "transactionType") or "").lower()
        side = "buy" if ttype in _BUY_TYPES else ("sell" if ttype.startswith("sale") or "sell" in ttype else None)
        if side is None:
            continue        # exchanges / unknown types carry no directional signal
        low, high = _parse_amount(_field(r, "amount"))
        out.append({
            "ticker": ticker,
            "member": _member_name(r),
            "chamber": chamber,
            "party": r.get("party"),
            "side": side,
            "amount_low": low,
            "amount_high": high,
            "transaction_date": str(_field(r, "transaction_date", "transactionDate") or ""),
            "disclosure_date": str(_field(r, "disclosure_date", "disclosureDate", "dateRecieved") or ""),
        })
    return out


def _midpoint(trade):
    return (trade["amount_low"] + trade["amount_high"]) / 2.0


def aggregate_by_ticker(trades):
    """Roll trades up per ticker: net direction by dollar weight, counts, recency."""
    agg = {}
    for t in trades:
        a = agg.setdefault(t["ticker"], {
            "n_buys": 0, "n_sells": 0, "buy_dollars": 0.0, "sell_dollars": 0.0,
            "total_low": 0.0, "total_high": 0.0, "members": set(),
            "most_recent_disclosure": "",
        })
        a["members"].add(t["member"])
        a["total_low"] += t["amount_low"]
        a["total_high"] += t["amount_high"]
        if t["side"] == "buy":
            a["n_buys"] += 1
            a["buy_dollars"] += _midpoint(t)
        else:
            a["n_sells"] += 1
            a["sell_dollars"] += _midpoint(t)
        d = _parse_date(t["disclosure_date"])
        cur = _parse_date(a["most_recent_disclosure"])
        if d is not None and (cur is None or d > cur):
            a["most_recent_disclosure"] = t["disclosure_date"]

    for ticker, a in agg.items():
        a["n_members"] = len(a.pop("members"))
        a["net_side"] = "buy" if a["buy_dollars"] >= a["sell_dollars"] else "sell"
    return agg


def recent_large_trades(trades, min_amount, lookback_days, today=None):
    """Trades at/above min_amount (upper bound) disclosed within lookback_days — the
    'big buy/sale on any given day' discovery feed."""
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=lookback_days)
    out = []
    for t in trades:
        if t["amount_high"] < min_amount:
            continue
        d = _parse_date(t["disclosure_date"])
        if d is None or d < cutoff:
            continue
        out.append(t)
    out.sort(key=lambda t: t["amount_high"], reverse=True)
    return out


_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAdvisor/1.0"
FMP_BASE = "https://financialmodelingprep.com/stable"


def _http_json(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmp_fetch(api_key) -> dict:
    """Latest House + Senate disclosures from Financial Modeling Prep (free key)."""
    house, senate = [], []
    try:
        senate = _http_json(f"{FMP_BASE}/senate-latest?apikey={api_key}")
    except Exception:
        pass
    try:
        house = _http_json(f"{FMP_BASE}/house-latest?apikey={api_key}")
    except Exception:
        pass
    return {"house": house, "senate": senate}


def _default_fetch() -> dict:
    """Fetch raw House + Senate disclosures. Network call — not unit-tested.

    Prefers Financial Modeling Prep when FMP_API_KEY is set (free, current data). Falls
    back to the legacy StockWatcher datasets, which no longer allow public access — so
    without a key the feed is typically empty and congress signals degrade out gracefully.
    """
    api_key = os.environ.get("FMP_API_KEY")
    if api_key:
        return _fmp_fetch(api_key)

    house, senate = [], []
    try:
        house = _http_json(HOUSE_URL)
    except Exception:
        pass
    try:
        senate = _http_json(SENATE_URL)
    except Exception:
        pass
    return {"house": house, "senate": senate}


def get_congress_trades(fetch=_default_fetch, cache_path=CACHE_PATH) -> list:
    """Return a normalized list of congressional trades, with cache fallback on outage.

    The cache holds the last good raw payload so a dataset hiccup degrades to the most
    recent snapshot rather than breaking the briefing.
    """
    cache_path = Path(cache_path)
    try:
        payload = fetch()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        if not cache_path.exists():
            return []
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return (_parse_congress(payload.get("house", []), "house")
            + _parse_congress(payload.get("senate", []), "senate"))
