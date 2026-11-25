"""The pre-registered short-interest study — docs/preregistration-short-interest.md, Amendment 1.

H1: short shares / shares outstanding, ranked across liquid US names, POSITIVELY predicts
+21-day excess return over SPY (size + volatility neutralised). Four checks, fixed in advance:
sign > 0, |Newey-West t| > 2.75, same sign in >= 3 of the 4 full years 2022-2025, |IC| >= 0.02.

This is a measurement, not a signal: nothing here touches the score. Run it on the machine that
holds the deep price cache:

    python -m src.short_interest [data_dir]   # fetch (cached), measure, print the verdict

Point-in-time rules, asserted rather than assumed:
- A FINRA reading is usable only from the 8th business day after its settlement date
  (FINRA publishes on the 7th).
- Shares outstanding come from SEC filings and are usable only from their FILING date.
- A short reading older than MAX_SI_AGE_DAYS, or shares outstanding older than
  MAX_SHARES_AGE_DAYS, is missing — never carried forward indefinitely.
"""
import json
import math
from pathlib import Path

import pandas as pd

PUBLICATION_LAG_BDAYS = 7          # FINRA publishes on the 7th business day after settlement
MAX_SI_AGE_DAYS = 35               # two bi-monthly cycles; older than this is stale
MAX_SHARES_AGE_DAYS = 400
PILOT_WINDOW = ("2026-07-28", "2026-09-09")
FULL_YEARS = (2022, 2023, 2024, 2025)
T_BAR, IC_FLOOR, YEARS_NEEDED = 2.75, 0.02, 3
PRIMARY_H = 21
HORIZONS = (5, 10, 21, 63)

FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
FINRA_PAGE = 5000
SEC_CONCEPT_URL = ("https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}"
                   "/dei/EntityCommonStockSharesOutstanding.json")


# ============================== point-in-time helpers ==============================

def usable_from(settlement) -> pd.Timestamp:
    """First session a reading settled on `settlement` may be used: the day after publication."""
    settlement = pd.Timestamp(settlement).normalize()
    usable = settlement + pd.offsets.BDay(PUBLICATION_LAG_BDAYS + 1)
    assert usable > settlement + pd.offsets.BDay(PUBLICATION_LAG_BDAYS), "look-ahead"
    return usable


def _num(v):
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")
    return x


def _yf_symbol(sym):
    """FINRA 'BRK.B' / 'BRK/B' -> yfinance 'BRK-B'."""
    return str(sym).strip().upper().replace(".", "-").replace("/", "-")


def _first(rec, *keys):
    for k in keys:
        if rec.get(k) not in (None, ""):
            return rec[k]
    return None


def normalise_finra(records) -> pd.DataFrame:
    """FINRA rows (current API or legacy file field names) -> one tidy frame."""
    out = []
    for r in records:
        sym = _first(r, "symbolCode", "issueSymbolIdentifier")
        settle = _first(r, "settlementDate")
        if not sym or not settle:
            continue
        out.append({
            "ticker": _yf_symbol(sym),
            "settlement": pd.Timestamp(settle).normalize(),
            "short_shares": _num(_first(r, "currentShortPositionQuantity",
                                        "currentShortShareNumber")),
            "avg_volume": _num(_first(r, "averageDailyVolumeQuantity",
                                      "averageShortShareNumber")),
            "days_to_cover": _num(_first(r, "daysToCoverQuantity", "daysToCoverNumber")),
        })
    cols = ["ticker", "settlement", "short_shares", "avg_volume", "days_to_cover"]
    return pd.DataFrame(out, columns=cols)


def shares_outstanding_series(payload) -> list:
    """SEC companyconcept JSON -> [(filed, shares)] sorted by filing date."""
    rows = ((payload or {}).get("units") or {}).get("shares") or []
    pts = sorted({(pd.Timestamp(r["filed"]), float(r["val"]))
                  for r in rows if r.get("filed") and r.get("val") is not None})
    return pts


def _asof(points, dates, max_age_days):
    """Latest value with timestamp <= date and no older than max_age_days, else NaN."""
    if not points:
        return pd.Series(float("nan"), index=dates)
    s = pd.Series([v for _, v in points], index=pd.DatetimeIndex([d for d, _ in points]))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    stamp = pd.Series(s.index, index=s.index)
    val = s.reindex(s.index.union(dates)).ffill().reindex(dates)
    when = stamp.reindex(stamp.index.union(dates)).ffill().reindex(dates)
    age = (pd.Series(dates, index=dates) - when).dt.days
    return val.where(age <= max_age_days)


def build_signal(si_rows, shares_by_ticker, dates, tickers):
    """(short/shares-outstanding, days-to-cover) as date x ticker panels, point-in-time."""
    dates = pd.DatetimeIndex(dates)
    ratio, dtc = {}, {}
    by_t = {t: g for t, g in si_rows.groupby("ticker")} if len(si_rows) else {}
    for t in tickers:
        g = by_t.get(t)
        if g is None or g.empty:
            ratio[t] = dtc[t] = pd.Series(float("nan"), index=dates)
            continue
        when = [usable_from(s) for s in g["settlement"]]
        short = _asof(list(zip(when, g["short_shares"])), dates, MAX_SI_AGE_DAYS)
        dtc[t] = _asof(list(zip(when, g["days_to_cover"])), dates, MAX_SI_AGE_DAYS)
        shares = _asof(shares_by_ticker.get(t, []), dates, MAX_SHARES_AGE_DAYS)
        ratio[t] = short / shares.where(shares > 0)
    return pd.DataFrame(ratio, index=dates), pd.DataFrame(dtc, index=dates)


# ============================== the verdict ==============================

def verdict(primary) -> dict:
    """Apply the four pre-registered checks to the +21d result. No discretion here."""
    ic, t = primary.get("ic"), primary.get("t")
    years = primary.get("by_year") or {}
    pos_years = sum(1 for y in FULL_YEARS if (years.get(y) or {}).get("ic", 0) > 0)
    checks = {
        "sign": ic is not None and ic > 0,
        "t": t is not None and abs(t) > T_BAR,
        "years": pos_years >= YEARS_NEEDED,
        "size": ic is not None and abs(ic) >= IC_FLOOR,
    }
    if all(checks.values()):
        outcome = "PASS"
    elif ic is not None and ic < 0 and checks["t"]:
        outcome = "NEGATIVE_SIGNIFICANT"
    elif checks["sign"] and checks["size"] and not (checks["t"] and checks["years"]):
        outcome = "UNDERPOWERED"
    else:
        outcome = "REJECTED"
    return {"outcome": outcome, "checks": checks, "positive_full_years": pos_years}


# ============================== network seams (run on the owner's machine) ====================

def _http_post_json(url, body, timeout=60):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    return json.loads(text) if text.strip() else []


def _sec_get_json(url):
    """SEC through the edgar module's own client, which owns the required User-Agent."""
    import urllib.error
    from src import edgar
    try:
        return edgar._http_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:                     # no such concept for this filer
            return {}
        raise


def fetch_finra(start, end, universe, cache_dir, post=_http_post_json):
    """All FINRA readings for `universe` between start and end, cached one file per month."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    want = set(universe)
    frames = []
    for m in pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M"):
        f = cache_dir / f"finra-{m}.csv"
        if f.exists() and m < pd.Timestamp.today().to_period("M"):
            frames.append(pd.read_csv(f, parse_dates=["settlement"]))
            continue
        recs, offset = [], 0
        while True:
            body = {"dateRangeFilters": [{"fieldName": "settlementDate",
                                          "startDate": str(m.start_time.date()),
                                          "endDate": str(m.end_time.date())}],
                    "limit": FINRA_PAGE, "offset": offset}
            page = post(FINRA_URL, body)
            recs.extend(page)
            if len(page) < FINRA_PAGE:
                break
            offset += FINRA_PAGE
        df = normalise_finra(recs)
        df = df[df["ticker"].isin(want)]
        df.to_csv(f, index=False)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else normalise_finra([])


def fetch_shares(tickers, cik_map, cache_file, get=_sec_get_json):
    """{ticker: [(filed, shares)]} from SEC, cached to one JSON file."""
    import time
    cache_file = Path(cache_file)
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    for t in tickers:
        if t in cache:
            continue
        cik = cik_map.get(t) or cik_map.get(t.replace("-", "."))
        if not cik:
            cache[t] = []
            continue
        payload = get(SEC_CONCEPT_URL.format(cik=int(cik)))
        cache[t] = [(d.strftime("%Y-%m-%d"), v) for d, v in shares_outstanding_series(payload)]
        time.sleep(0.12)                      # SEC fair-access: stay under 10 requests/second
    cache_file.write_text(json.dumps(cache))
    return {t: [(pd.Timestamp(d), float(v)) for d, v in pts] for t, pts in cache.items()}


# ============================== CLI ==============================

def _fmt(v, places=4):
    return "  n/a " if v is None else f"{v:+.{places}f}"


def run(data_dir="data"):
    from src import research

    scores, closes, bench = research._load_price_panel(data_dir)
    if closes is None:
        return "no deep price panel — run scripts/fetch_deep_history.py first"
    _, volumes = __import__("scripts.score_panel", fromlist=["load_panel"]).load_panel(
        str(data_dir), min_bars=800)
    tickers = [t for t in closes.columns if t != research.BENCHMARK]
    start = pd.Timestamp.today() - pd.DateOffset(years=5)
    si_rows = fetch_finra(start, pd.Timestamp.today(), tickers,
                          Path(data_dir) / "short_interest")
    from src import edgar
    cik_map = edgar.load_cik_map()
    shares = fetch_shares(tickers, cik_map, Path(data_dir) / "short_interest" / "shares.json")
    ratio, dtc = build_signal(si_rows, shares, closes.index, tickers)

    lines = [f"FINRA rows: {len(si_rows)} for {si_rows['ticker'].nunique()} tickers, "
             f"{si_rows['settlement'].min().date()} .. {si_rows['settlement'].max().date()}",
             f"names with a usable ratio on the last date: {int(ratio.iloc[-1].notna().sum())}", ""]
    results = {}
    for label, panel in (("short / shares outstanding (PRIMARY)", ratio),
                         ("days to cover (secondary)", dtc)):
        for cut, excl in (("all dates", None), ("excluding pilot window", PILOT_WINDOW)):
            res = research.panel_rank_ic(panel, closes, volumes, bench, horizons=HORIZONS,
                                         neutralize=True, exclude=excl, by_year=True)
            results[(label, cut)] = res
            lines.append(f"{label} — {cut}")
            for h in HORIZONS:
                r = res[h]
                lines.append(f"  {h:>2}d  IC {_fmt(r['ic'])}  t {_fmt(r['t'], 2)}  "
                             f"days {r['n_days']}  IC>0 {(r['hit_rate'] or 0) * 100:.0f}%")
            for y, v in sorted(res[PRIMARY_H]["by_year"].items()):
                lines.append(f"      {y}  21d IC {_fmt(v['ic'])}  days {v['n_days']}")
    v_all = verdict(results[("short / shares outstanding (PRIMARY)", "all dates")][PRIMARY_H])
    v_cut = verdict(results[("short / shares outstanding (PRIMARY)",
                             "excluding pilot window")][PRIMARY_H])
    lines += ["", f"VERDICT (all dates): {v_all['outcome']}  checks={v_all['checks']}",
              f"VERDICT (pilot window excluded): {v_cut['outcome']}  checks={v_cut['checks']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(run(sys.argv[1] if len(sys.argv) > 1 else "data"))
