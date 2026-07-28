"""EDGAR 8-K event study, run against the pre-registration in
docs/preregistration-8k-event-study.md.

Design: on each rebalance date, split the eligible cross-section into names WITH the event
in the trailing 30 days and names WITHOUT, and take the difference in mean forward excess
return over SPY. That contrast is the estimate; t-tested across NON-OVERLAPPING dates.

Point-in-time: an event dated d is visible only on bars STRICTLY AFTER d, mirroring
edgar.signal_asof. Reuses edgar's own _SEVERE/_NEGATIVE/_CATALYST tables so the study measures
the same definitions the app ships.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import edgar  # noqa: E402
import score_panel as sp  # noqa: E402

WINDOW = 30          # trailing calendar days an event stays "live" (matches sec_window_days)
MIN_EVENT_NAMES = 5  # skip a date with too thin an event group to average


def build_event_flags(filings, index, columns):
    """-> {event_name: bool DataFrame(index=dates, columns=tickers)}."""
    kinds = ["catalyst", "negative", "severe", "activist", "form4"]
    flags = {k: pd.DataFrame(False, index=index, columns=columns) for k in kinds}
    idx = pd.DatetimeIndex(index)
    for tk in columns:
        rec = filings.get(tk)
        if not rec:
            continue
        events = {k: [] for k in kinds}
        for form, item_str, d in zip(rec["form"], rec["items"], rec["date"]):
            form = str(form or "").strip()
            try:
                fd = pd.Timestamp(str(d)[:10])
            except Exception:
                continue
            if form == "8-K":
                for code in edgar._explode_items(item_str):
                    if code in edgar._SEVERE:
                        events["severe"].append(fd)
                    elif code in edgar._NEGATIVE:
                        events["negative"].append(fd)
                    elif code in edgar._CATALYST:
                        events["catalyst"].append(fd)
            elif form in ("SC 13D", "SC 13D/A"):
                events["activist"].append(fd)
            elif form == "4":
                events["form4"].append(fd)
        for k, ds in events.items():
            if not ds:
                continue
            col = np.zeros(len(idx), dtype=bool)
            for fd in ds:
                # STRICTLY after the filing date -> no same-day look-ahead
                lo = idx.searchsorted(fd, side="right")
                hi = idx.searchsorted(fd + pd.Timedelta(days=WINDOW), side="right")
                if lo < len(idx):
                    col[lo:hi] = True
            flags[k].loc[:, tk] = col
    return flags


def spread_series(flag, X, elig, h):
    """Per-date (mean excess of event names) - (mean excess of non-event names)."""
    out, dates = [], []
    for d in X.index[252::h]:                       # non-overlapping, after indicator warmup
        x = X.loc[d]
        e = elig.loc[d]
        f = flag.loc[d]
        ev = x[e & f].dropna()
        nv = x[e & ~f].dropna()
        if len(ev) < MIN_EVENT_NAMES or len(nv) < 20:
            continue
        out.append(ev.mean() - nv.mean())
        dates.append(d)
    return pd.Series(out, index=pd.DatetimeIndex(dates))


def report(name, s, predicted_sign):
    if len(s) < 8:
        print(f"  {name:26} n={len(s):3d}  INSUFFICIENT")
        return None
    m = s.mean()
    t = m / (s.std(ddof=1) / math.sqrt(len(s)))
    by_year = s.groupby(s.index.year).mean()
    yrs = by_year.loc[[y for y in by_year.index if 2020 <= y <= 2025]]
    consistent = int((np.sign(yrs) == predicted_sign).sum())
    ok_sign = np.sign(m) == predicted_sign
    ok_t = abs(t) > 2.75
    ok_cons = consistent >= 4
    ok_size = abs(m) >= 0.30
    verdict = "PASS" if (ok_sign and ok_t and ok_cons and ok_size) else "fail"
    marks = f"sign{'+' if ok_sign else '-'} t{'+' if ok_t else '-'} yrs{consistent}/6 size{'+' if ok_size else '-'}"
    print(f"  {name:26} n={len(s):3d}  {m:+7.3f}%  t={t:+6.2f}   {marks:28} {verdict}")
    return {"mean": m, "t": t, "n": len(s), "years": consistent, "verdict": verdict}


def main():
    C, V = sp.load_panel(str(REPO / "data"))
    S = sp.panel_scores(C, V)
    elig = S.notna()
    bench = C["SPY"]
    filings = json.loads((REPO / "data" / "edgar_filings.json").read_text(encoding="utf-8"))
    print(f"panel {C.shape[1]} tickers x {C.shape[0]} bars   filings for {len(filings)} tickers")

    flags = build_event_flags(filings, C.index, C.columns)
    cov = {k: float(v.loc[elig.index].where(elig).sum().sum()) for k, v in flags.items()}
    tot = float(elig.sum().sum())
    print("event coverage (share of eligible name-days):")
    for k, v in cov.items():
        print(f"    {k:10} {v / tot * 100:5.2f}%")
    print()

    hyps = [("catalyst", +1, "H1 8-K catalyst"), ("negative", -1, "H2 8-K negative"),
            ("severe", -1, "H3 8-K severe"), ("activist", +1, "H4 13D activist"),
            ("form4", +1, "H5 Form 4 intensity")]
    for h in (5, 21, 63):
        r = C.shift(-h) / C - 1.0
        b = bench.shift(-h) / bench - 1.0
        X = r.sub(b, axis=0) * 100.0
        star = "  <-- PRIMARY" if h == 21 else ""
        print(f"+{h}d excess vs SPY, event-minus-nonevent spread{star}")
        for key, sign, label in hyps:
            report(label, spread_series(flags[key], X, elig, h), sign)
        print()
    print("Bar (pre-registered): sign matches AND |t|>2.75 AND >=4/6 years AND |mean|>=0.30%")


if __name__ == "__main__":
    main()
