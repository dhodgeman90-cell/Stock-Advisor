"""Rank-IC harness: does a signal actually order tomorrow's returns?

Why this exists
---------------
`data/signal_history.jsonl` has captured every enrichment signal point-in-time since
2026-07-28, plus a random control cohort, and nothing in the repo read it. The scorecard
grades *picks* (binary fired/not-fired alpha deltas on the ledger); nothing measured whether a
CONTINUOUS signal ranks the cross-section. That is the question that decides whether a signal
belongs in the score, so it needs a permanent, tested home rather than a throwaway script.

The one methodological point that matters
-----------------------------------------
The first pass at this data said `base_score` was ANTI-predictive (5d IC -0.078). It is not.
The shortlist trades at a median $275M/day against $497M/day for its own pool -- a persistent
0.55x small/illiquid tilt -- and that six-week window was a large-cap tape. Project size and
volatility out of both the signal and the return and the IC collapses to -0.033 / -0.003:
noise, not inverted alpha. So `neutralize=True` is not a nicety here; without it you measure
the market's factor tape and mistake it for skill. `options.vol_oi_ratio` is the cautionary
case: raw IC +0.070/+0.094, neutralised +0.007/-0.003. It was entirely size.

Everything reports `n_days` beside the estimate, and the t-stat is Newey-West with lag = the
horizon, because overlapping forward windows are autocorrelated by construction. Below
`_MIN_DAYS_FOR_T` cross-sections the t is `None` rather than a number -- a t-stat on 9
overlapping days is arithmetic, not evidence.
"""
import json
import math
from pathlib import Path

from src import data

BENCHMARK = "SPY"
_VOL_WINDOW = 21          # bars for realised volatility and average dollar volume
_MIN_DAYS_FOR_T = 10      # fewer cross-sections than this -> report no t-stat at all
_MIN_BLOCKS_FOR_T = 2     # and require this many NON-overlapping windows (n_days >= k*horizon)


# ============================== small statistics ==============================

def _ranks(xs):
    """Fractional ranks in 0..1, ties sharing the average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return [r / len(xs) for r in out]


def _pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / math.sqrt(va * vb)


def _residuals(y, controls):
    """y regressed on `controls` (list of equal-length lists) plus an intercept.

    Plain Gauss-Jordan on the normal equations: the design is 3 columns wide, so the numerical
    fragility that would matter at scale does not arise. Returns None if the system is
    singular (e.g. a control is constant within the day), which the caller treats as
    "cannot neutralise this day" and skips.
    """
    n, k = len(y), len(controls)
    X = [[1.0] + [controls[c][i] for c in range(k)] for i in range(n)]
    m = k + 1
    A = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(m)]
         + [sum(X[i][a] * y[i] for i in range(n))] for a in range(m)]
    for c in range(m):
        p = max(range(c, m), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-10:
            return None
        A[c], A[p] = A[p], A[c]
        pv = A[c][c]
        A[c] = [x / pv for x in A[c]]
        for r in range(m):
            if r != c and A[r][c] != 0:
                f = A[r][c]
                A[r] = [A[r][j] - f * A[c][j] for j in range(m + 1)]
    beta = [A[i][m] for i in range(m)]
    return [y[i] - sum(beta[j] * X[i][j] for j in range(m)) for i in range(n)]


def newey_west(series, lag):
    """(mean, t) for a series of daily estimates, corrected for overlap-induced autocorrelation.

    Overlapping k-day forward windows share k-1 days of returns, so consecutive daily ICs are
    mechanically correlated and a plain t-stat overstates significance -- often by a lot. Bartlett
    weights out to `lag` deflate it.

    Two floors, and below either one the t is None rather than a number. The first is an
    absolute count. The second is the one that matters: `n_days / lag` is roughly how many
    NON-overlapping windows the sample really contains, and with fewer than a couple of them
    Newey-West is arithmetic on itself. On this repo's own data the 21d column had 9 overlapping
    cross-sections and produced t = +29.4 and t = -6.4 -- numbers that look like overwhelming
    evidence and mean nothing. Printing them would repeat the exact mistake this module exists
    to prevent, so they are withheld and the point estimate stands alone.
    """
    n = len(series)
    if n < _MIN_DAYS_FOR_T or n < _MIN_BLOCKS_FOR_T * max(1, lag):
        return (sum(series) / n if n else None), None
    mean = sum(series) / n
    e = [x - mean for x in series]
    var = sum(x * x for x in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        cov = sum(e[i] * e[i - L] for i in range(L, n)) / n
        var += 2 * (1 - L / (lag + 1)) * cov
    if var <= 0:
        return mean, None
    return mean, mean / math.sqrt(var / n)


# ============================== panel construction ==============================

def _dig(row, path):
    """'signals.analyst.upside_pct' -> the value, or None if any hop is missing/null."""
    cur = row
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _load_prices(data_dir, tickers):
    out = {}
    for t in tickers:
        # load_cache applies data._drop_incomplete, so a partial live bar can never enter a
        # study the same way it must never enter a score.
        df = data.load_cache(t, data_dir)
        if df is not None and len(df) > _VOL_WINDOW:
            out[t] = df
    return out


def forward_panel(data_dir, horizons=(5, 10, 21), benchmark=BENCHMARK, history_file=None):
    """signal_history.jsonl x cached prices -> rows with forward excess returns and controls.

    Each row is the original capture plus `fwd_<h>` (return over h trading bars minus the
    benchmark's over the same bars), `size` (log mean dollar volume) and `vol` (realised
    volatility). Rows whose forward window has not closed are dropped for that horizon, and a
    row missing the longest horizon still keeps the shorter ones.
    """
    data_dir = Path(data_dir)
    path = Path(history_file) if history_file else data_dir / "signal_history.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue          # tolerate a torn final line, same as signal_log.load_signals
    if not records:
        return []

    bench = data.load_cache(benchmark, data_dir)
    if bench is None or len(bench) == 0:
        return []
    bench_close = bench["Close"]
    cal = [d.strftime("%Y-%m-%d") for d in bench.index]
    pos = {d: i for i, d in enumerate(cal)}

    prices = _load_prices(data_dir, sorted({r.get("ticker") for r in records if r.get("ticker")}))

    rows = []
    for rec in records:
        t, d = rec.get("ticker"), rec.get("date")
        df = prices.get(t)
        if df is None or d not in pos:
            continue
        close = df["Close"]
        idx = {x.strftime("%Y-%m-%d"): i for i, x in enumerate(df.index)}
        if d not in idx:
            continue
        i, bi = idx[d], pos[d]
        row = dict(rec)
        row["size"], row["vol"] = _size(df, i), _vol(close, i)
        kept = False
        for h in horizons:
            j, bj = i + h, bi + h
            if j >= len(close) or bj >= len(bench_close):
                continue
            r_name = float(close.iloc[j]) / float(close.iloc[i]) - 1.0
            r_bench = float(bench_close.iloc[bj]) / float(bench_close.iloc[bi]) - 1.0
            row[f"fwd_{h}"] = r_name - r_bench
            kept = True
        if kept:
            rows.append(row)
    return rows


def _size(df, i):
    """log of mean dollar volume over the trailing window — the size/liquidity control."""
    lo = max(0, i - _VOL_WINDOW + 1)
    dollars = (df["Close"] * df["Volume"]).iloc[lo:i + 1]
    m = float(dollars.mean())
    return math.log(m) if m > 0 else None


def _vol(close, i):
    """realised volatility over the trailing window — the risk control."""
    lo = max(1, i - _VOL_WINDOW + 1)
    rets = [float(close.iloc[k]) / float(close.iloc[k - 1]) - 1.0 for k in range(lo, i + 1)]
    if len(rets) < 10:
        return None
    m = sum(rets) / len(rets)
    return math.sqrt(sum((x - m) ** 2 for x in rets) / len(rets))


# ============================== the measurements ==============================

def _by_date(rows, horizon, cohorts=None):
    key = f"fwd_{horizon}"
    out = {}
    for r in rows:
        if cohorts and r.get("cohort") not in cohorts:
            continue
        if r.get(key) is None:
            continue
        out.setdefault(r["date"], []).append(r)
    return out


def rank_ic(rows, signal, horizon, *, neutralize=False, min_names=10, cohorts=None):
    """Mean daily Spearman IC of `signal` against the forward excess return.

    `signal` is a dotted path into a panel row ("base_score", "signals.short.pct_float").
    `neutralize=True` projects `size` and `vol` out of BOTH the signal and the return, which is
    what separates a real edge from a factor tilt — see the module docstring.

    Returns {ic, t, n_days, hit_rate, n_obs}. `t` is None when there are too few cross-sections
    to support one; `ic` is None when no day qualified.
    """
    key = f"fwd_{horizon}"
    ics, n_obs = [], 0
    for date in sorted(_by_date(rows, horizon, cohorts)):
        day = _by_date(rows, horizon, cohorts)[date]
        xs, ys, sz, vl = [], [], [], []
        for r in day:
            v = _dig(r, signal)
            if v is None:
                continue
            if neutralize and (r.get("size") is None or r.get("vol") is None):
                continue
            xs.append(float(v))
            ys.append(float(r[key]))
            sz.append(float(r.get("size") or 0.0))
            vl.append(float(r.get("vol") or 0.0))
        if len(xs) < min_names or len({*xs}) < 3:
            continue
        n_obs += len(xs)
        rx, ry = _ranks(xs), _ranks(ys)
        if neutralize:
            # A control that is constant within the day carries no information and would make
            # the design matrix singular against the intercept. Drop it rather than losing the
            # whole day — on real data `vol` is occasionally flat for a thin name.
            controls = [c for c in (_ranks(sz), _ranks(vl)) if len(set(c)) > 1]
            if controls:
                rx, ry = _residuals(rx, controls), _residuals(ry, controls)
                if rx is None or ry is None:
                    continue      # still singular (collinear controls) -> can't neutralise today
        ic = _pearson(rx, ry)
        if ic is None and neutralize:
            # No residual variation left in the signal (or in the return) once the controls are
            # projected out. That is a real answer, not missing data: this signal adds nothing
            # beyond size and volatility. Score it as exactly zero edge.
            ic = 0.0
        if ic is not None:
            ics.append(ic)
    if not ics:
        return {"ic": None, "t": None, "n_days": 0, "hit_rate": None, "n_obs": 0}
    mean, t = newey_west(ics, horizon)
    return {"ic": mean, "t": t, "n_days": len(ics),
            "hit_rate": sum(1 for x in ics if x > 0) / len(ics), "n_obs": n_obs}


def cohort_contrast(rows, horizon, *, min_names=5):
    """Mean forward excess return of the candidate cohort vs the random control cohort.

    The control names are drawn at random from the eligible pool each day, so this is the one
    unbiased read on whether the whole selection funnel — pre-filter, score, enrichment — beats
    picking names out of a hat. Returns {candidate, control, diff, t, n_days}.
    """
    key = f"fwd_{horizon}"
    cand, ctrl, diffs = [], [], []
    grouped = _by_date(rows, horizon)
    for date in sorted(grouped):
        day = grouped[date]
        c = [r[key] for r in day if r.get("cohort") == "candidate"]
        x = [r[key] for r in day if r.get("cohort") == "control"]
        if len(c) < min_names or len(x) < min_names:
            continue
        mc, mx = sum(c) / len(c), sum(x) / len(x)
        cand.append(mc)
        ctrl.append(mx)
        diffs.append(mc - mx)
    if not diffs:
        return {"candidate": None, "control": None, "diff": None, "t": None, "n_days": 0}
    mean, t = newey_west(diffs, horizon)
    return {"candidate": sum(cand) / len(cand), "control": sum(ctrl) / len(ctrl),
            "diff": mean, "t": t, "n_days": len(diffs)}


# ============================== CLI ==============================

_REPORT_SIGNALS = [
    ("base_score (the app's own ranking)", "base_score"),
    ("analyst upside_pct", "signals.analyst.upside_pct"),
    ("analyst coverage n", "signals.analyst.n_analysts"),
    ("short pct_float", "signals.short.pct_float"),
    ("options vol_oi_ratio", "signals.options.vol_oi_ratio"),
    ("edgar form4_count", "signals.edgar.form4_count"),
]


def _fmt(v, pct=False, places=3):
    if v is None:
        return "  n/a "
    return f"{v * 100:+.2f}%" if pct else f"{v:+.{places}f}"


def report(data_dir="data", horizons=(5, 10, 21)):
    """Print the IC table, raw and neutralised, plus the cohort contrast."""
    rows = forward_panel(data_dir, horizons=horizons)
    if not rows:
        return "no panel rows — is data/signal_history.jsonl present and are prices cached?"
    out = [f"panel: {len(rows)} rows, {len({r['date'] for r in rows})} dates, "
           f"{len({r['ticker'] for r in rows})} tickers", ""]
    out.append("Candidate cohort vs RANDOM control (the unbiased read on the whole funnel):")
    for h in horizons:
        c = cohort_contrast(rows, h)
        out.append(f"  {h:2d}d  candidate {_fmt(c['candidate'], pct=True)}  "
                   f"control {_fmt(c['control'], pct=True)}  diff {_fmt(c['diff'], pct=True)}  "
                   f"t={_fmt(c['t'], places=2)}  n_days={c['n_days']}")
    out += ["", "Rank IC — RAW vs SIZE+VOL-NEUTRALISED (neutralised is the one to believe):"]
    for label, path in _REPORT_SIGNALS:
        out.append(f"  {label}")
        for h in horizons:
            a = rank_ic(rows, path, h)
            b = rank_ic(rows, path, h, neutralize=True)
            out.append(f"    {h:2d}d  raw IC={_fmt(a['ic'])} t={_fmt(a['t'], places=2)}   "
                       f"neutral IC={_fmt(b['ic'])} t={_fmt(b['t'], places=2)}   "
                       f"n_days={a['n_days']}")
    out += ["", "A t-stat rests on n_days OVERLAPPING cross-sections. Below ~20 of them, read",
            "the point estimate and ignore the t. This window cannot fit weights — only falsify."]
    return "\n".join(out)


def demo():
    """ponytail: one runnable check the statistics are right."""
    rows = [{"date": f"2026-08-{d:02d}", "ticker": f"T{i}", "cohort": "candidate",
             "base_score": float(i), "fwd_5": float(i), "size": 0.0, "vol": 0.0}
            for d in range(3, 13) for i in range(20)]
    assert abs(rank_ic(rows, "base_score", 5)["ic"] - 1.0) < 1e-9
    for r in rows:                       # make the signal pure size
        r["size"] = r["base_score"]
    assert abs(rank_ic(rows, "base_score", 5, neutralize=True)["ic"]) < 1e-6
    print("research.demo OK")


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        demo()
    else:
        print(report())
