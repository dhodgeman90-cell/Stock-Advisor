"""Options-flow signal from free yfinance option chains (no paid feed).

A simple read on where near-term option activity is leaning: the put/call *volume*
ratio (direction) and total volume vs. open interest (how unusual today's flow is). A
call-heavy, high-turnover tape is a bullish confirm; put-heavy is a caution.

Pure `_parse_options()` (unit-tested) + thin networked `get_options_signal()` that
degrades to a no-opinion default on failure — same shape as insights.py.

ponytail: this is the free ~80% of "options flow." Real-time institutional sweeps /
dark-pool prints are premium-only (Unusual Whales, Quant Data ~$40-65/mo) and were
explicitly out of scope. Upgrade path is to swap _default_fetch for such a feed.
"""
import math

# Standard put/call-volume read. <0.7 = call-heavy (bullish), >1.3 = put-heavy (bearish).
PC_BULLISH = 0.7
PC_BEARISH = 1.3
NEAR_EXPIRIES = 2          # aggregate the two nearest expiries — where the flow concentrates

NEUTRAL_OPTIONS = {
    "pc_ratio": None, "call_volume": 0, "put_volume": 0,
    "total_oi": 0, "vol_oi_ratio": 0.0, "direction": "neutral",
}


def _num(x) -> float:
    """yfinance leaves NaN in volume/OI cells; coerce to a clean float (NaN -> 0)."""
    try:
        v = float(x)
        return 0.0 if math.isnan(v) else v
    except (TypeError, ValueError):
        return 0.0


def _parse_options(calls, puts) -> dict:
    """Aggregate call/put volume + open interest into one signal (pure, testable).

    `calls`/`puts` are lists of dicts with 'volume' and 'openInterest'. Direction uses
    the standard put/call volume thresholds; `vol_oi_ratio` (turnover) lets the caller
    gate on how unusual the flow is.
    """
    call_vol = sum(_num(r.get("volume")) for r in calls)
    put_vol = sum(_num(r.get("volume")) for r in puts)
    total_oi = sum(_num(r.get("openInterest")) for r in calls) \
        + sum(_num(r.get("openInterest")) for r in puts)

    pc_ratio = (put_vol / call_vol) if call_vol else None
    total_vol = call_vol + put_vol
    vol_oi_ratio = (total_vol / total_oi) if total_oi else 0.0

    direction = "neutral"
    if pc_ratio is not None:
        if pc_ratio < PC_BULLISH:
            direction = "bullish"
        elif pc_ratio > PC_BEARISH:
            direction = "bearish"

    return {
        "pc_ratio": round(pc_ratio, 3) if pc_ratio is not None else None,
        "call_volume": int(call_vol), "put_volume": int(put_vol),
        "total_oi": int(total_oi), "vol_oi_ratio": round(vol_oi_ratio, 3),
        "direction": direction,
    }


def _default_fetch(ticker):
    """Pull the nearest expiries' call/put volume + OI from yfinance. Network — not tested."""
    import yfinance as yf
    tk = yf.Ticker(ticker)
    expiries = (tk.options or [])[:NEAR_EXPIRIES]
    calls, puts = [], []
    for exp in expiries:
        chain = tk.option_chain(exp)
        calls += chain.calls[["volume", "openInterest"]].to_dict("records")
        puts += chain.puts[["volume", "openInterest"]].to_dict("records")
    return calls, puts


def get_options_signal(ticker, fetch=_default_fetch) -> dict:
    """Options-flow signal for one ticker; no-opinion default on any failure.

    Heavy call (full option chains), so the engine only runs it for shortlisted
    candidates and holdings — not the whole watchlist.
    """
    try:
        calls, puts = fetch(ticker)
        return _parse_options(calls or [], puts or [])
    except Exception:
        return dict(NEUTRAL_OPTIONS)
