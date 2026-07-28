"""Fetch point-in-time EDGAR filing history for the whole scan universe.

Writes data/edgar_filings.json: {ticker: {"form": [...], "items": [...], "date": [...]}}
covering 2019-01-01 onward. Heavy filers (big banks) truncate `filings.recent` to ~1 year,
so their older archive files are pulled too — without that, 8-K coverage would be systematically
thinner for large financials in early years, which is a bias, not a gap.

SEC asks for <=10 req/s and a descriptive User-Agent; this throttles to ~6/s.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import config, edgar, profile as P  # noqa: E402

START = "2019-01-01"
THROTTLE = 1 / 6.0

prof = P.Profile.for_repo()
out_path = prof.data_dir / "edgar_filings.json"

cik_map = edgar.load_cik_map()
universe = sorted(set(config.load_universe(prof.config_dir) or [])
                  | set(config.load_watchlist(prof.config_dir)["tickers"]))
print(f"universe {len(universe)}, cik map {len(cik_map)}", flush=True)

out = {}
if out_path.exists():
    out = json.loads(out_path.read_text(encoding="utf-8"))
    print(f"resuming: {len(out)} tickers already cached", flush=True)

no_cik = extra = done = 0
for i, t in enumerate(universe):
    if t in out:
        continue
    cik = cik_map.get(t)
    if not cik:
        no_cik += 1
        continue
    try:
        j = edgar._http_json(edgar.SUBMISSIONS_URL.format(cik=int(cik)))
    except Exception as e:
        print(f"  {t}: {type(e).__name__}", flush=True)
        time.sleep(THROTTLE)
        continue
    rec = j["filings"]["recent"]
    forms = list(rec.get("form", []))
    items = list(rec.get("primaryDocDescription", [])) or [""] * len(forms)
    items = list(rec.get("items", [])) if rec.get("items") else items
    dates = list(rec.get("filingDate", []))
    time.sleep(THROTTLE)

    # Heavy filer? `recent` did not reach back to START -> pull the older archive files.
    if dates and min(dates) > START:
        for f in j["filings"].get("files", []):
            if f.get("filingTo", "") < START:
                continue
            try:
                a = edgar._http_json(f"https://data.sec.gov/submissions/{f['name']}")
            except Exception:
                time.sleep(THROTTLE)
                continue
            forms += list(a.get("form", []))
            items += list(a.get("items", [])) if a.get("items") else [""] * len(a.get("form", []))
            dates += list(a.get("filingDate", []))
            extra += 1
            time.sleep(THROTTLE)

    keep = [(f, it, d) for f, it, d in zip(forms, items, dates) if d >= START]
    out[t] = {"form": [k[0] for k in keep], "items": [k[1] for k in keep],
              "date": [k[2] for k in keep]}
    done += 1
    if done % 50 == 0:
        print(f"  {done} fetched ({i + 1}/{len(universe)}), {extra} archive files", flush=True)
        out_path.write_text(json.dumps(out), encoding="utf-8")

out_path.write_text(json.dumps(out), encoding="utf-8")
spans = [(min(v["date"]), max(v["date"])) for v in out.values() if v["date"]]
print(f"DONE: {len(out)} tickers, {no_cik} without a CIK, {extra} archive files pulled", flush=True)
if spans:
    print(f"earliest filing across universe: {min(s[0] for s in spans)}", flush=True)
    reach = sum(1 for s in spans if s[0] <= "2019-06-30")
    print(f"tickers whose history reaches 2019H1: {reach}/{len(spans)}", flush=True)
