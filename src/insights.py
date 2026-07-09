"""Per-ticker insight signals sourced from yfinance (already a dependency).

Each signal is a pure `_parse_*()` (unit-tested) plus a thin networked `get_*()` that
pulls from yfinance and degrades to a no-opinion default on any failure — matching the
graceful-fallback style of news.py / the agents.
"""
import datetime as dt

NEUTRAL_ANALYST = {"rating": None, "mean": None, "target": None,
                   "upside_pct": None, "n_analysts": 0}
NEUTRAL_INSIDER = {"net_side": None, "n_buys": 0, "n_sells": 0,
                   "buy_value": 0.0, "sell_value": 0.0}
NEUTRAL_EARNINGS = {"next_earnings": None, "days_until": None}
NEUTRAL_SHORT = {"pct_float": None, "days_to_cover": None,
                 "shares_short": None, "rising": None}


# --- analyst ratings / price targets --------------------------------------
def _parse_analyst(info, current_price):
    """Distill yfinance .info into a consensus rating + target upside."""
    target = info.get("targetMeanPrice")
    upside = None
    if target is not None and current_price:
        upside = (float(target) - float(current_price)) / float(current_price) * 100.0
    return {
        "rating": info.get("recommendationKey"),
        "mean": info.get("recommendationMean"),
        "target": float(target) if target is not None else None,
        "upside_pct": upside,
        "n_analysts": int(info.get("numberOfAnalystOpinions") or 0),
    }


def _default_analyst_fetch(ticker):
    import yfinance as yf
    tk = yf.Ticker(ticker)
    info = tk.info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    return info, price


def get_analyst_signal(ticker, fetch=_default_analyst_fetch) -> dict:
    try:
        info, current_price = fetch(ticker)
        return _parse_analyst(info or {}, current_price)
    except Exception:
        return dict(NEUTRAL_ANALYST)


# --- corporate insider (Form 4) buying ------------------------------------
def _parse_insider(records):
    """Net officer buying vs selling from yfinance insider-transaction rows."""
    n_buys = n_sells = 0
    buy_value = sell_value = 0.0
    for r in records:
        action = str(r.get("Transaction") or "").lower()
        value = float(r.get("Value") or 0)
        if "purchase" in action or action == "buy":
            n_buys += 1
            buy_value += value
        elif "sale" in action or action == "sell":
            n_sells += 1
            sell_value += value
    net_side = None
    if n_buys or n_sells:
        net_side = "buy" if buy_value >= sell_value else "sell"
    return {"net_side": net_side, "n_buys": n_buys, "n_sells": n_sells,
            "buy_value": buy_value, "sell_value": sell_value}


def _default_insider_fetch(ticker):
    import yfinance as yf
    df = yf.Ticker(ticker).insider_transactions
    if df is None or getattr(df, "empty", True):
        return []
    return df.to_dict("records")


def get_insider_signal(ticker, fetch=_default_insider_fetch) -> dict:
    try:
        return _parse_insider(fetch(ticker) or [])
    except Exception:
        return dict(NEUTRAL_INSIDER)


# --- earnings gap guard ----------------------------------------------------
def _coerce_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(str(value), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _parse_earnings(calendar, today=None):
    """Soonest upcoming earnings date and days until, from yfinance .calendar."""
    today = today or dt.date.today()
    raw = (calendar or {}).get("Earnings Date") or []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    future = sorted(d for d in (_coerce_date(x) for x in raw) if d is not None and d >= today)
    if not future:
        return dict(NEUTRAL_EARNINGS)
    nxt = future[0]
    return {"next_earnings": nxt.isoformat(), "days_until": (nxt - today).days}


def _default_earnings_fetch(ticker):
    import yfinance as yf
    return yf.Ticker(ticker).calendar or {}


def get_earnings(ticker, fetch=_default_earnings_fetch) -> dict:
    try:
        return _parse_earnings(fetch(ticker))
    except Exception:
        return dict(NEUTRAL_EARNINGS)


# --- short interest / squeeze setup ---------------------------------------
def _parse_short(info, today=None, fresh_days=45):
    """Short-interest read from yfinance .info (already a free field — no new source).

    `shortPercentOfFloat` is a 0-1 fraction (0.1439 = 14.39%); we surface it as a
    percent. `shortRatio` is days-to-cover. `rising` compares this month's short shares
    to the prior month so the adjudicator can tell a building short from a covering one.

    `fresh` uses yfinance's `dateShortInterest` (the exchange report date): exchange short
    interest is reported ~twice a month with a lag, so a report older than `fresh_days` is
    stale and the adjudicator drops the squeeze/crowded-short call. Defaults True when the
    date is missing (can't prove staleness → keep the old behavior).
    """
    pct = info.get("shortPercentOfFloat")
    pct_float = float(pct) * 100.0 if pct is not None else None
    shares = info.get("sharesShort")
    prior = info.get("sharesShortPriorMonth")
    rising = None
    if shares is not None and prior is not None:
        rising = float(shares) > float(prior)
    dtc = info.get("shortRatio")
    fresh = True
    ts = info.get("dateShortInterest")
    if ts:
        try:
            report_date = dt.date.fromtimestamp(int(ts))
            fresh = ((today or dt.date.today()) - report_date).days <= fresh_days
        except (ValueError, OverflowError, OSError):
            fresh = True
    return {
        "pct_float": round(pct_float, 2) if pct_float is not None else None,
        "days_to_cover": float(dtc) if dtc is not None else None,
        "shares_short": int(shares) if shares is not None else None,
        "rising": rising,
        "fresh": fresh,
    }


def get_short_signal(ticker, fetch=_default_analyst_fetch) -> dict:
    """Short-interest signal for one ticker; no-opinion default on any failure.

    ponytail: reuses the analyst .info fetch (same endpoint) — short interest is just
    more fields on the same payload, so no extra source and no extra network shape.
    """
    try:
        info, _ = fetch(ticker)
        return _parse_short(info or {})
    except Exception:
        return dict(NEUTRAL_SHORT)


# --- analyst estimate-revision momentum -----------------------------------
NEUTRAL_REVISION = {"revision_trend": "flat", "n_up": 0, "n_down": 0}


def _parse_revisions(records, today=None, window_days=90):
    """Net analyst revision direction over a recent window (pure, testable).

    A *static* consensus rating misses the momentum that actually moves stocks: the
    drift of upgrades/downgrades and price-target raises/cuts. We tally both signals
    (rating action + price-target action) inside the window and net them.
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=window_days)
    n_up = n_down = 0
    for r in records:
        d = _coerce_date(r.get("GradeDate"))
        if d is None or d < cutoff:
            continue
        action = str(r.get("Action") or "").lower()
        pta = str(r.get("priceTargetAction") or "").lower()
        if action == "up" or pta.startswith("rais"):
            n_up += 1
        elif action == "down" or pta.startswith("low"):
            n_down += 1
    trend = "flat"
    if n_up > n_down and n_up >= 2:
        trend = "up"
    elif n_down > n_up and n_down >= 2:
        trend = "down"
    return {"revision_trend": trend, "n_up": n_up, "n_down": n_down}


def _default_revision_fetch(ticker):
    import yfinance as yf
    df = yf.Ticker(ticker).upgrades_downgrades
    if df is None or getattr(df, "empty", True):
        return []
    return df.reset_index().to_dict("records")


def get_revision_signal(ticker, fetch=_default_revision_fetch) -> dict:
    try:
        return _parse_revisions(fetch(ticker) or [])
    except Exception:
        return dict(NEUTRAL_REVISION)
