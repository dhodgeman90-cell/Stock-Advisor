"""Market-regime input from the VIX and sector-ETF breadth.

Sharpens the existing context_agent's regime call (and provides a deterministic regime
when no API key is set) using two cheap, broad reads: the VIX fear gauge and how many
S&P sector ETFs are green today. Both come from yfinance.
"""

import pandas as pd

from src import indicators

# Standard SPDR sector ETFs — a quick read on how broad today's move is.
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]

VIX_CALM = 16.0     # below this, fear is low
VIX_FEAR = 25.0     # above this, fear is elevated
BROAD_UP = 0.60     # fraction of sectors green that counts as broad strength
BROAD_DOWN = 0.35   # fraction green below which breadth is weak

NEUTRAL_BREADTH = {
    "vix": None, "vix_change": None, "pct_sectors_up": None,
    "regime": "neutral", "regime_hint": "market breadth unavailable",
}


def _summarize_breadth(vix, vix_prev, sector_changes):
    """Classify the market regime from VIX level + sector breadth (pure, testable)."""
    changes = list((sector_changes or {}).values())
    pct_up = (sum(1 for c in changes if c > 0) / len(changes)) if changes else None
    vix_change = (vix - vix_prev) if (vix is not None and vix_prev is not None) else None

    regime = "neutral"
    if (vix is not None and vix > VIX_FEAR) or (pct_up is not None and pct_up < BROAD_DOWN):
        regime = "risk_off"
    elif (vix is not None and vix < VIX_CALM) and (pct_up is not None and pct_up > BROAD_UP):
        regime = "risk_on"

    vix_txt = f"VIX {vix:.1f}" if vix is not None else "VIX n/a"
    breadth_txt = f"{pct_up * 100:.0f}% of sectors green" if pct_up is not None else "breadth n/a"
    return {
        "vix": vix,
        "vix_change": vix_change,
        "pct_sectors_up": pct_up,
        "regime": regime,
        "regime_hint": f"{vix_txt}; {breadth_txt}.",
    }


def _default_fetch() -> dict:
    """Pull VIX (last two closes) and one-day sector ETF changes. Network — not unit-tested."""
    import yfinance as yf

    def _last_two_closes(symbol):
        hist = yf.Ticker(symbol).history(period="5d")
        closes = list(hist["Close"].dropna())
        return (closes[-1], closes[-2]) if len(closes) >= 2 else (None, None)

    vix, vix_prev = _last_two_closes("^VIX")
    sector_changes = {}
    for etf in SECTOR_ETFS:
        last, prev = _last_two_closes(etf)
        if last is not None and prev:
            sector_changes[etf] = (last - prev) / prev * 100.0
    return {"vix": vix, "vix_prev": vix_prev, "sector_changes": sector_changes}


def get_market_breadth(fetch=_default_fetch) -> dict:
    try:
        raw = fetch()
        return _summarize_breadth(raw.get("vix"), raw.get("vix_prev"), raw.get("sector_changes"))
    except Exception:
        return dict(NEUTRAL_BREADTH)


# --- macro overlay: yield curve + credit spread ----------------------------
# Two of the most-watched recession/stress reads, both free & keyless:
#   * 10Y-3M Treasury curve (^TNX - ^IRX) — inversion is the classic recession lead
#   * BofA US High-Yield OAS (FRED BAMLH0A0HYM2) — credit stress / risk appetite
CURVE_INVERTED = 0.0      # 10Y minus 3M below this = inverted
CREDIT_STRESS = 5.0       # HY option-adjusted spread (%) above this = stressed credit

NEUTRAL_MACRO = {"yield_curve": None, "hy_spread": None,
                 "macro_regime": "neutral", "macro_hint": "macro data unavailable"}


def _assess_macro(curve, hy_spread):
    """Classify a macro risk overlay from the yield curve + HY credit spread (pure)."""
    flags = []
    if curve is not None and curve < CURVE_INVERTED:
        flags.append("yield curve inverted")
    if hy_spread is not None and hy_spread >= CREDIT_STRESS:
        flags.append(f"credit spread {hy_spread:.1f}% (stressed)")
    macro_regime = "risk_off" if flags else "neutral"
    if flags:
        hint = "; ".join(flags) + "."
    else:
        curve_txt = f"10Y-3M {curve:+.2f}" if curve is not None else "curve n/a"
        hy_txt = f"HY spread {hy_spread:.1f}%" if hy_spread is not None else "HY n/a"
        hint = f"{curve_txt}; {hy_txt}."
    return {"yield_curve": curve, "hy_spread": hy_spread,
            "macro_regime": macro_regime, "macro_hint": hint}


def _default_macro_fetch() -> dict:
    """10Y-3M Treasury curve (yfinance ^TNX/^IRX) + HY credit spread (FRED keyless CSV)."""
    import urllib.request
    import yfinance as yf

    def _last_close(symbol):
        closes = list(yf.Ticker(symbol).history(period="5d")["Close"].dropna())
        return closes[-1] if closes else None

    tnx, irx = _last_close("^TNX"), _last_close("^IRX")
    curve = (tnx - irx) if (tnx is not None and irx is not None) else None

    hy_spread = None
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
    req = urllib.request.Request(url, headers={"User-Agent": "StockAdvisor/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        rows = [r for r in resp.read().decode("utf-8").strip().splitlines() if r]
    for line in reversed(rows[1:]):          # last non-header row with a numeric value
        val = line.split(",")[-1].strip()
        if val and val != ".":
            hy_spread = float(val)
            break
    return {"curve": curve, "hy_spread": hy_spread}


def get_macro_context(fetch=_default_macro_fetch) -> dict:
    """Macro risk overlay (yield curve + credit spread); neutral default on failure."""
    try:
        raw = fetch()
        return _assess_macro(raw.get("curve"), raw.get("hy_spread"))
    except Exception:
        return dict(NEUTRAL_MACRO)


# --- point-in-time regime series (Phase 1) ---------------------------------
# The snapshot readers above answer "what's the regime TODAY?" for the live briefing.
# The backtest instead needs "what was the regime as-of every PAST bar?" — computable
# with no look-ahead and no per-bar network. regime_series does that from SPY alone;
# apply_hysteresis smooths it so exposure doesn't whipsaw on a single red day.
# ponytail: SPY-only MVP. A higher-fidelity regime_series_full (feeding as-of VIX +
# sector breadth + yield-curve/HY into _summarize_breadth/_assess_macro, worst-of) is
# deferred until Phase-2 validation shows the SPY-only signal is too crude to justify it.

def regime_series(spy_df, *, fast=50, slow=200, dd_thresh=8.0):
    """Per-date market regime {"risk_on","neutral","risk_off"} from SPY, as-of safe.

    risk_off when price is below the slow MA AND drawdown-from-trailing-high exceeds
    dd_thresh%; risk_on when price > fast MA > slow MA; neutral otherwise (including the
    slow-MA warm-up, where we never cut exposure without a signal). Every value at bar i
    uses only bars <= i (rolling means + cummax), so regime_series(spy[:k])[-1] equals
    regime_series(spy)[k-1] — no future data leaks into a past decision."""
    close = spy_df["Close"].astype(float)
    sma_fast = indicators.sma(close, fast)
    sma_slow = indicators.sma(close, slow)
    drawdown = (close / close.cummax() - 1.0) * 100.0     # <= 0, percent below trailing high
    out = []
    for c, sf, ss, dd in zip(close, sma_fast, sma_slow, drawdown):
        if pd.isna(ss):
            out.append("neutral")                          # slow MA not warmed up -> no signal
        elif c < ss and dd < -dd_thresh:
            out.append("risk_off")
        elif not pd.isna(sf) and c > sf > ss:
            out.append("risk_on")
        else:
            out.append("neutral")
    return pd.Series(out, index=close.index)


def apply_hysteresis(raw, *, confirm_down=3, confirm_up=5):
    """Smooth a raw regime Series into a two-state exposure stance {"risk_on","risk_off"}.

    Starts risk_on (fully invested). Cuts to risk_off only after confirm_down consecutive
    risk_off bars; restores to risk_on only after confirm_up consecutive non-risk_off bars
    (neutral counts as non-risk_off). Re-entry is deliberately slower than exit. This is
    what stops a single red day from flipping exposure — the whipsaw that makes naive
    market-timing lose to buy-and-hold."""
    out = []
    state = "risk_on"
    down = up = 0
    for r in raw:
        if r == "risk_off":
            down += 1
            up = 0
        else:
            up += 1
            down = 0
        if state != "risk_off" and down >= confirm_down:
            state = "risk_off"
        elif state == "risk_off" and up >= confirm_up:
            state = "risk_on"
        out.append(state)
    return pd.Series(out, index=raw.index)
