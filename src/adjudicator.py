from src import trust

_ANALYST_BULL = {"strong_buy", "buy"}
_ANALYST_BEAR = {"sell", "strong_sell", "underperform"}


def adjudicate(candidate: dict, news: dict, risk: dict, context: dict, caps: dict, *,
               congress=None, wsb=None, social_view=None,
               analyst=None, insider=None, earnings=None, thresholds=None) -> dict:
    """Combine the deterministic score with every signal source. Pure function.

    Veto wins absolutely. Every other source contributes a capped, symmetric adjustment;
    the final score is clamped 0-100. New sources (congress, insider, analyst, earnings,
    r/wallstreetbets) are optional keyword args so the original call sites keep working.
    Social media is scaled by a situational trust score (trust.social_trust) so it only
    counts as much as it deserves *in this specific setup*.
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
    }
