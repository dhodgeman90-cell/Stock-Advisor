from src import trust

_ANALYST_BULL = {"strong_buy", "buy"}
_ANALYST_BEAR = {"sell", "strong_sell", "underperform"}


def adjudicate(candidate: dict, news: dict, risk: dict, context: dict, caps: dict, *,
               congress=None, wsb=None, social_view=None,
               analyst=None, insider=None, earnings=None, thresholds=None,
               edgar=None, options=None, short=None, revision=None) -> dict:
    """Combine the deterministic score with every signal source. Pure function.

    Veto wins absolutely. Every other source contributes a capped, symmetric adjustment;
    the final score is clamped 0-100. New sources (congress, insider, analyst, earnings,
    r/wallstreetbets, SEC EDGAR filings, options flow, short interest, estimate revisions)
    are optional keyword args so the original call sites keep working. Social media is
    scaled by a situational trust score (trust.social_trust) so it only counts as much as
    it deserves *in this specific setup*.
    """
    thresholds = thresholds or {}
    ticker = candidate["ticker"]
    base = float(candidate["score"])
    regime = context.get("regime", "neutral")

    if risk.get("veto"):
        return {
            "ticker": ticker, "base_score": base, "final_score": base,
            "vetoed": True, "veto_reason": risk.get("reason", ""),
            "news": news, "risk": risk, "regime": regime, "adjustments": [],
            "congress": congress, "social": None, "social_trust": None,
            "analyst": analyst, "insider": insider, "earnings": earnings,
            "edgar": edgar, "options": options, "short": short, "revision": revision,
        }

    final = base
    adjustments = []

    level = risk.get("risk_level", "low")
    if level == "high":
        final -= caps["risk_high"]
        adjustments.append(f"-{caps['risk_high']:.0f} high risk")
    elif level == "medium":
        final -= caps["risk_medium"]
        adjustments.append(f"-{caps['risk_medium']:.0f} medium risk")

    if news.get("catalyst"):
        final += caps["catalyst"]
        adjustments.append(f"+{caps['catalyst']:.0f} catalyst")
    if news.get("sentiment") == "neg":
        final -= caps["news_negative"]
        adjustments.append(f"-{caps['news_negative']:.0f} negative news")

    if regime == "risk_off":
        final -= caps["regime"]
        adjustments.append(f"-{caps['regime']:.0f} risk-off market")
    elif regime == "risk_on":
        final += caps["regime"]
        adjustments.append(f"+{caps['regime']:.0f} risk-on market")

    # ---- Congress (weighted heavily, per the owner) ----
    if congress and congress.get("net_side") == "buy":
        final += caps["congress_buy"]
        adjustments.append(f"+{caps['congress_buy']:.0f} congress buying ({congress.get('n_members', 1)})")
    elif congress and congress.get("net_side") == "sell":
        final -= caps["congress_sell"]
        adjustments.append(f"-{caps['congress_sell']:.0f} congress selling ({congress.get('n_members', 1)})")

    # ---- Corporate insider (Form 4) ----
    if insider and insider.get("net_side") == "buy":
        final += caps["insider_buy"]
        adjustments.append(f"+{caps['insider_buy']:.0f} insider buying")
    elif insider and insider.get("net_side") == "sell":
        final -= caps["insider_sell"]
        adjustments.append(f"-{caps['insider_sell']:.0f} insider selling")

    # ---- Analyst consensus / price targets ----
    if analyst and analyst.get("rating"):
        rating = analyst["rating"]
        upside = analyst.get("upside_pct")
        if rating in _ANALYST_BEAR or (upside is not None and upside < -5):
            final -= caps["analyst"]
            adjustments.append(f"-{caps['analyst']:.0f} analysts bearish")
        elif rating in _ANALYST_BULL and (upside is None or upside > 0):
            final += caps["analyst"]
            adjustments.append(f"+{caps['analyst']:.0f} analysts bullish")

    # ---- Earnings gap guard (demote NEW entries near a print) ----
    days = (earnings or {}).get("days_until")
    if days is not None and days <= thresholds.get("earnings_window_days", 5):
        final -= caps["earnings_soon"]
        adjustments.append(f"-{caps['earnings_soon']:.0f} earnings in {days}d")

    # ---- SEC EDGAR filings (primary-source catalysts + activist stakes) ----
    # Additive caps use .get() defaults so an older adjudicator.yaml (predating these
    # sources) keeps working — same forgiving style as the thresholds above.
    if edgar:
        if edgar.get("severe"):
            sev = caps.get("risk_high", 20)
            final -= sev
            adjustments.append(f"-{sev:.0f} SEC: {edgar.get('severe_reason') or 'severe filing'}")
        if edgar.get("catalyst"):
            cap = caps.get("edgar_catalyst", 15)
            final += cap
            kinds = ", ".join(edgar.get("catalyst_types") or []) or "8-K"
            adjustments.append(f"+{cap:.0f} SEC 8-K ({kinds})")
        elif edgar.get("negative"):
            cap = caps.get("edgar_catalyst", 15)
            final -= cap
            adjustments.append(f"-{cap:.0f} SEC 8-K (adverse)")
        if edgar.get("activist"):
            cap = caps.get("activist_stake", 12)
            final += cap
            adjustments.append(f"+{cap:.0f} activist 13D stake")

    # ---- Options flow (free yfinance chains; only when volume is real & unusual) ----
    if options:
        total_vol = (options.get("call_volume") or 0) + (options.get("put_volume") or 0)
        unusual = (options.get("vol_oi_ratio") or 0) >= thresholds.get("options_unusual_ratio", 0.5)
        if total_vol >= thresholds.get("options_min_volume", 1000) and unusual:
            cap = caps.get("options_flow", 8)
            if options.get("direction") == "bullish":
                final += cap
                adjustments.append(f"+{cap:.0f} unusual call flow")
            elif options.get("direction") == "bearish":
                final -= cap
                adjustments.append(f"-{cap:.0f} unusual put flow")

    # ---- Short interest: squeeze setup (corroborated) vs crowded short (weak chart) ----
    if short and short.get("pct_float") is not None \
            and short["pct_float"] >= thresholds.get("short_high_pct", 20):
        cap = caps.get("short_squeeze", 10)
        wsb_rising = bool(wsb and (wsb.get("mentions_change") or 0) > 0)
        if base >= 60 or wsb_rising:
            final += cap
            adjustments.append(f"+{cap:.0f} squeeze setup ({short['pct_float']:.0f}% short)")
        else:
            final -= cap
            adjustments.append(f"-{cap:.0f} crowded short ({short['pct_float']:.0f}% short)")

    # ---- Analyst estimate-revision momentum (drift beats a static rating) ----
    if revision:
        cap = caps.get("estimate_revision", 5)
        if revision.get("revision_trend") == "up":
            final += cap
            adjustments.append(f"+{cap:.0f} estimates rising")
        elif revision.get("revision_trend") == "down":
            final -= cap
            adjustments.append(f"-{cap:.0f} estimates falling")

    # ---- r/wallstreetbets, scaled by situational trust ----
    social_trust = None
    social_summary = None
    min_mentions = thresholds.get("social_min_mentions", 25)
    if wsb and (wsb.get("mentions") or 0) >= min_mentions:
        social_view = social_view or {}
        credibility = social_view.get("credibility")
        contrarian = bool(social_view.get("contrarian"))
        social_trust = trust.social_trust(wsb, base, congress, insider, risk, credibility)
        applied = round(caps["social"] * social_trust, 2)
        rising = (wsb.get("mentions_change") or 0) > 0 or (wsb.get("rank_change") or 0) > 0
        if contrarian and applied:
            final -= applied
            social_summary = f"-{applied:g} WSB hype (contrarian, trust {social_trust:.0%})"
        elif rising and applied:
            final += applied
            social_summary = f"+{applied:g} WSB buzz (trust {social_trust:.0%})"
        if social_summary:
            adjustments.append(social_summary)

    final = max(0.0, min(100.0, final))

    return {
        "ticker": ticker, "base_score": base, "final_score": final,
        "vetoed": False, "veto_reason": "",
        "news": news, "risk": risk, "regime": regime, "adjustments": adjustments,
        "congress": congress, "social": social_summary, "social_trust": social_trust,
        "analyst": analyst, "insider": insider, "earnings": earnings,
        "edgar": edgar, "options": options, "short": short, "revision": revision,
    }
