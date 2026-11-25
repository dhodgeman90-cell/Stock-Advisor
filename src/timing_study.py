"""The pre-registered overlay drawdown test — docs/preregistration-overlay-drawdown.md.

Three ways to hold SPY, on SPY's own history (no survivorship possible):
  B&H      always in
  MONTHLY  the shipped market call (market.monthly_trend_call), re-decided at month-ends
  OVERLAY  market.apply_hysteresis(market.regime_series(...)), checked daily

A stance on day t is the position held from t's close to t+1's close, so it earns t+1's return
and never its own. Out of the market earns 0%. Each switch costs COST.

    python -m src.timing_study [data_dir]
"""
from pathlib import Path

import pandas as pd

from src import market

COST = 0.001
STARTS = (1999, 2003, 2010, 2015)
CRISES = {
    "dot-com": ("2000-03-01", "2002-10-31"),
    "GFC": ("2007-10-01", "2009-03-31"),
    "COVID": ("2020-02-01", "2020-04-30"),
    "2022": ("2022-01-01", "2022-12-31"),
}
DD_RATIO_MAX = 0.75
B_NEEDED = 3


# ============================== stances ==============================

def monthly_stance(close) -> pd.Series:
    """True = invested. Decided at each month-end close vs its 200-day SMA and effective from the
    first session of the next month — the morning the briefing shows it. Invested during warm-up
    (no signal, no cut), as the overlay does."""
    close = close.astype(float)
    sma = close.rolling(200).mean()
    idx = close.index
    month_end = pd.Series(idx.to_period("M"), index=idx)
    is_me = month_end.ne(month_end.shift(-1))
    is_me.iloc[-1] = False                    # the current month is not over
    out = pd.Series(float("nan"), index=idx)
    positions = [i for i, flag in enumerate(is_me) if flag]
    for i in positions:
        if i + 1 < len(idx) and not pd.isna(sma.iloc[i]):
            out.iloc[i + 1] = 1.0 if close.iloc[i] > sma.iloc[i] else 0.0
    return out.ffill().fillna(1.0).astype(bool)


def overlay_stance(close) -> pd.Series:
    """True = invested: the shipped regime overlay with its default hysteresis."""
    regime = market.apply_hysteresis(market.regime_series(pd.DataFrame({"Close": close})))
    return regime != "risk_off"


# ============================== equity + metrics ==============================

def equity(close, stance, cost=COST) -> pd.Series:
    close = close.astype(float)
    ret = close.pct_change().fillna(0.0)
    held = stance.astype(bool).shift(1, fill_value=False)
    gross = 1.0 + ret.where(held, 0.0)
    switched = stance.astype(bool).ne(stance.astype(bool).shift(1))
    switched.iloc[0] = False
    charge = pd.Series(1.0, index=close.index).where(~switched, 1.0 - cost)
    eq = (gross * charge).cumprod()
    return eq / eq.iloc[0]


def switches(stance) -> int:
    s = stance.astype(bool)
    return int(s.ne(s.shift(1)).iloc[1:].sum())


def metrics(eq, switches=0) -> dict:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    dd = float((eq / eq.cummax() - 1.0).min())
    if dd == 0:
        ret_dd = float("inf") if cagr > 0 else 0.0
    elif cagr >= 0:
        ret_dd = cagr / abs(dd)
    else:
        ret_dd = cagr * abs(dd)               # sign-aware, like backtest._ret_per_dd
    return {"cagr": float(cagr), "max_dd": dd, "ret_dd": float(ret_dd),
            "switches_per_year": switches / years if years > 0 else 0.0}


# ============================== verdict ==============================

def verdict(per_start) -> dict:
    a = all(abs(r["overlay"]["max_dd"]) <= DD_RATIO_MAX * abs(r["bh"]["max_dd"])
            for r in per_start.values())
    b_wins = sum(1 for r in per_start.values()
                 if r["overlay"]["ret_dd"] > r["monthly"]["ret_dd"])
    b = b_wins >= B_NEEDED
    outcome = ("PROPOSE_OVERLAY" if a and b else "KEEP_MONTHLY" if a else "RETIRE_OVERLAY")
    return {"outcome": outcome, "checks": {"A": a, "B": b}, "b_wins": b_wins}


# ============================== run ==============================

def _window(close, start, end, stances):
    sl = close.loc[start:end]
    out = {"bh": metrics(equity(sl, pd.Series(True, index=sl.index)), 0)}
    for name, st in stances.items():
        s = st.loc[sl.index]
        out[name] = metrics(equity(sl, s), switches(s))
    return out


def run_on(close) -> dict:
    close = close.astype(float).dropna()
    stances = {"monthly": monthly_stance(close), "overlay": overlay_stance(close)}
    last_me = close.index[close.index < close.index[-1].to_period("M").start_time][-1]
    per_start, notes = {}, []
    earliest = (close.index[0] + pd.Timedelta(days=300)).year + 1   # first Jan 1 after warm-up
    starts = list(STARTS)
    if earliest > STARTS[0]:
        # Pre-registered: the earliest supported start replaces 1999 when the cache is shorter.
        notes.append(f"history begins {close.index[0].date()}: 1999 start not supported, "
                     f"replaced by {earliest}")
        starts = [earliest] + [y for y in STARTS[1:] if y > earliest]
        notes += [f"{y} start not supported" for y in STARTS[1:] if y <= earliest]
    for y in starts:
        per_start[y] = _window(close, pd.Timestamp(f"{y}-01-01"), last_me, stances)
    crises = {k: _window(close, a, b, stances) for k, (a, b) in CRISES.items()
              if close.index[0] <= pd.Timestamp(a) - pd.Timedelta(days=300)}
    return {"per_start": per_start, "crises": crises, "notes": notes, "end": last_me,
            "begin": close.index[0], "verdict": verdict(per_start) if per_start else None}


def render(res) -> str:
    L = [f"SPY {res['begin'].date()} .. {res['end'].date()} (through last completed month)"]
    L += [f"note: {n}" for n in res["notes"]]
    L += ["", f"{'period':<10} {'rule':<8} {'CAGR':>7} {'maxDD':>7} {'CAGR/DD':>8} {'sw/yr':>6}"]
    for label, rows in [(f"from {y}", r) for y, r in res["per_start"].items()] + \
                       list(res["crises"].items()):
        for name in ("bh", "monthly", "overlay"):
            m = rows[name]
            L.append(f"{label:<10} {name:<8} {m['cagr'] * 100:>6.1f}% {m['max_dd'] * 100:>6.1f}% "
                     f"{m['ret_dd']:>8.2f} {m['switches_per_year']:>6.1f}")
    v = res["verdict"]
    if v:
        L += ["", f"VERDICT: {v['outcome']}  A(drawdown<=75% of B&H everywhere)={v['checks']['A']}"
                  f"  B(beats monthly on CAGR/DD in >=3 of 4)={v['checks']['B']} ({v['b_wins']} wins)"]
    return "\n".join(L)


def load_spy(data_dir="data"):
    """SPY closes: the deep longhistory file spliced onto the current daily cache.

    longhistory reaches back decades but stops when it was last filled; the daily cache is
    current but short. The pre-registration says "through the last completed month", so both
    are needed. data._merge_history does the splice on the recent file's adjustment basis (and
    refuses to splice if the overlap is not a clean re-adjustment).
    """
    from src import data

    frames = []
    for p in (Path(data_dir) / "longhistory" / "SPY.csv", Path(data_dir) / "SPY.csv"):
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.columns = [c.capitalize() for c in df.columns]
            frames.append(df)
    if not frames:
        return None
    merged = frames[0]
    for df in frames[1:]:
        merged = data._merge_history(merged, df)
    return merged["Close"]


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    spy = load_spy(sys.argv[1] if len(sys.argv) > 1 else "data")
    print("no SPY history found" if spy is None else render(run_on(spy)))
