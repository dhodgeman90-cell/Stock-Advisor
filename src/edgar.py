"""SEC EDGAR filing signals, read straight from SEC's free JSON API (no key, no SDK).

Where the News agent *infers* catalysts from headlines, this reads the primary source:
the 8-K item codes a company files when something material happens. We also surface
activist stakes (Schedule 13D) and raw insider-filing (Form 4) intensity.

Two network endpoints, both keyless (SEC only asks for a descriptive User-Agent):
  * company_tickers.json   -> ticker -> CIK map (changes rarely; cached locally)
  * submissions/CIK#.json  -> a company's recent filings with form types + 8-K items

Pure `_parse_filings()` (unit-tested) + thin networked `get_sec_signal()` that degrades
to a no-opinion default on any failure, matching insights.py / social.py.

ponytail: raw urllib + stdlib json, no `edgartools` (it drags in pyarrow/lxml/bm25 —
~30MB for features we don't use). The one thing this can't cheaply do is 13F
"which funds hold ticker X" (needs a reverse index across thousands of filers);
that's deferred — it's quarterly with a 45-day lag, the weakest of the EDGAR signals.
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIK_CACHE_PATH = ROOT / "data" / "sec_cik_map.json"

# SEC asks for a User-Agent that identifies the app + a contact. (Generic UA -> 403.)
SEC_UA = "StockAdvisor/1.0 (dhodgeman90@gmail.com)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

DEFAULT_WINDOW_DAYS = 30

# 8-K item codes grouped by what they mean for a swing trade. Codes not listed here
# (5.07 shareholder votes, 9.01 exhibits, 7.01/8.01 FD/other) are routine and ignored.
# Reference: SEC Form 8-K item index.
_SEVERE = {                          # existential — treat as elevated risk
    "1.03": "bankruptcy filing",
    "2.04": "debt default / acceleration",
    "3.01": "delisting notice",
    "4.02": "financial restatement",
}
_NEGATIVE = {                        # materially bad, not existential
    "1.02": "terminated a material agreement",
    "2.06": "material asset impairment",
    "4.01": "auditor change",
}
_CATALYST = {                        # material, forward-looking / often a mover
    "1.01": "entered a material agreement",
    "2.01": "completed an acquisition/disposition",
    "2.02": "reported earnings",
    "5.02": "executive/board change",
}

NEUTRAL_SEC = {
    "catalyst": False, "negative": False, "severe": False,
    "catalyst_types": [], "severe_reason": "",
    "activist": False, "activist_detail": "",
    "form4_count": 0, "as_of": None,
}


def _explode_items(raw) -> list:
    """An 8-K's `items` field is a comma string like '2.02,9.01'; return clean codes."""
    return [c.strip() for c in str(raw or "").split(",") if c.strip()]


def _parse_filings(forms, items, dates, *, today=None, window_days=DEFAULT_WINDOW_DAYS) -> dict:
    """Distill SEC `filings.recent` parallel arrays into one signal (pure, testable).

    `forms`, `items`, `dates` are the equal-length lists SEC returns (form type, 8-K
    item string, filing date 'YYYY-MM-DD'). Only filings within `window_days` count.
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=window_days)

    sig = dict(NEUTRAL_SEC)
    cat_types, latest = [], None
    for form, item_str, date_str in zip(forms, items, dates):
        try:
            fdate = dt.date.fromisoformat(str(date_str)[:10])
        except (ValueError, TypeError):
            continue
        if fdate < cutoff:
            continue
        latest = fdate if latest is None or fdate > latest else latest
        form = str(form or "").strip()

        if form == "8-K":
            for code in _explode_items(item_str):
                if code in _SEVERE:
                    sig["severe"] = True
                    sig["severe_reason"] = _SEVERE[code]
                    cat_types.append(_SEVERE[code])
                elif code in _NEGATIVE:
                    sig["negative"] = True
                    cat_types.append(_NEGATIVE[code])
                elif code in _CATALYST:
                    sig["catalyst"] = True
                    cat_types.append(_CATALYST[code])
        elif form in ("SC 13D", "SC 13D/A"):     # activist stake (13G is passive — ignored)
            sig["activist"] = True
            sig["activist_detail"] = "activist 13D filed"
        elif form == "4":
            sig["form4_count"] += 1

    # de-dupe types while preserving order
    sig["catalyst_types"] = list(dict.fromkeys(cat_types))
    sig["as_of"] = latest.isoformat() if latest else None
    return sig


# --- networked helpers -----------------------------------------------------
def _http_json(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_tickers_fetch():
    return _http_json(TICKERS_URL)


def load_cik_map(fetch=_default_tickers_fetch, cache_path=CIK_CACHE_PATH) -> dict:
    """Return {TICKER: cik_int}. Cached locally (the map changes rarely) so we pay the
    one ~10k-row download infrequently and degrade to the cache on any outage."""
    cache_path = Path(cache_path)
    try:
        payload = fetch()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        if not cache_path.exists():
            return {}
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in payload.values()}


def _default_submissions_fetch(cik):
    return _http_json(SUBMISSIONS_URL.format(cik=cik))


def get_sec_signal(ticker, cik_map, *, fetch=_default_submissions_fetch,
                   window_days=DEFAULT_WINDOW_DAYS, today=None) -> dict:
    """SEC filing signal for one ticker. `cik_map` comes from load_cik_map() (fetched
    once per run and shared across tickers). No-opinion default on any failure."""
    try:
        cik = (cik_map or {}).get(str(ticker).upper())
        if not cik:
            return dict(NEUTRAL_SEC)
        recent = fetch(cik).get("filings", {}).get("recent", {})
        return _parse_filings(
            recent.get("form", []), recent.get("items", []), recent.get("filingDate", []),
            today=today, window_days=window_days,
        )
    except Exception:
        return dict(NEUTRAL_SEC)
