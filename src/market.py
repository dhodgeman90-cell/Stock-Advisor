"""Market-regime input from the VIX and sector-ETF breadth.

Sharpens the existing context_agent's regime call (and provides a deterministic regime
when no API key is set) using two cheap, broad reads: the VIX fear gauge and how many
S&P sector ETFs are green today. Both come from yfinance.
"""

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
