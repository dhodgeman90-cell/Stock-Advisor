import math

from src import trust

_ANALYST_BULL = {"strong_buy", "buy"}
_ANALYST_BEAR = {"sell", "strong_sell", "underperform"}

# Diminishing returns on stacked positive signals. A single strong signal counts in full up
# to `_STACK_KNEE` (the largest single cap, congress at 18); only the SUM beyond that knee is
# compressed, asymptoting at `_STACK_CAP`. This stops a mediocre base chart from being piled
# to 100 by stacking congress+catalyst+SEC+options+... (the mechanism behind the inverted top
# band) without penalising a name that has one genuine catalyst. Negatives stay full-strength:
# a real risk should still be able to fully tank a name. Both are tunable priors (Phase D).
_STACK_KNEE = 18.0
_STACK_CAP = 30.0


def _soft_cap_positive(points: float, knee: float = _STACK_KNEE, cap: float = _STACK_CAP) -> float:
    """Positive points count in full up to `knee`; the excess is smoothly compressed so the
    total asymptotes at `cap`. Monotonic, so a 3-signal name still outranks a 1-signal name."""
    if points <= knee:
        return max(0.0, points)
    room = cap - knee
    if room <= 0:
        return min(points, cap)
    return knee + room * math.tanh((points - knee) / room)


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
            "ticker": ticker, "base_score": base, "final_score": base, "rank_score": base,
            "vetoed": True, "veto_reason": risk.get("reason", ""),
            "news": news, "risk": risk, "regime": regime, "adjustments": [],
            "adjustment_detail": [],
            "congress": congress, "social": None, "social_trust": None,
            "analyst": analyst, "insider": insider, "earnings": earnings,
            "edgar": edgar, "options": options, "short": short, "revision": revision,
        }

    final = base
    adjustments = []
    detail = []   # structured [{"key", "points"}] attribution, parallel to `adjustments`

    def note(key, points, label):
        """Record one adjustment in both the human-readable `adjustments` list and the
        structured `detail` (so the scorecard can attribute forward alpha per signal).
        Returns `points` so the arithmetic stays explicit at the call site:
        `final += note(...)` — a subtraction is just a negative `points`."""
        adjustments.append(label)
        detail.append({"key": key, "points": round(float(points), 2)})
        return points

    level = risk.get("risk_level", "low")
    if level == "high":
        final += note("risk_high", -caps["risk_high"], f"-{caps['risk_high']:.0f} high risk")
    elif level == "medium":
        final += note("risk_medium", -caps["risk_medium"], f"-{caps['risk_medium']:.0f} medium risk")

    if news.get("catalyst"):
        final += note("catalyst", caps["catalyst"], f"+{caps['catalyst']:.0f} catalyst")
    if news.get("sentiment") == "neg":
        final += note("news_negative", -caps["news_negative"], f"-{caps['news_negative']:.0f} negative news")

    if regime == "risk_off":
        final += note("regime_off", -caps["regime"], f"-{caps['regime']:.0f} risk-off market")
    elif regime == "risk_on":
        final += note("regime_on", caps["regime"], f"+{caps['regime']:.0f} risk-on market")

    # ---- Congress (weighted heavily, per the owner) ----
    # Gate on freshness: a disclosure months old (or an empty feed with no FMP key) must not
    # fire the single biggest lever. `fresh` defaults True so older callers/tests are unaffected.
    if congress and congress.get("fresh", True) and congress.get("net_side") == "buy":
        final += note("congress_buy", caps["congress_buy"],
                      f"+{caps['congress_buy']:.0f} congress buying ({congress.get('n_members', 1)})")
    elif congress and congress.get("fresh", True) and congress.get("net_side") == "sell":
        final += note("congress_sell", -caps["congress_sell"],
                      f"-{caps['congress_sell']:.0f} congress selling ({congress.get('n_members', 1)})")

    # ---- Corporate insider (Form 4) ----
    if insider and insider.get("net_side") == "buy":
        final += note("insider_buy", caps["insider_buy"], f"+{caps['insider_buy']:.0f} insider buying")
    elif insider and insider.get("net_side") == "sell":
        final += note("insider_sell", -caps["insider_sell"], f"-{caps['insider_sell']:.0f} insider selling")

    # ---- Analyst consensus / price targets ----
    if analyst and analyst.get("rating"):
        rating = analyst["rating"]
        upside = analyst.get("upside_pct")
        if rating in _ANALYST_BEAR or (upside is not None and upside < -5):
            final += note("analyst_bear", -caps["analyst"], f"-{caps['analyst']:.0f} analysts bearish")
        elif rating in _ANALYST_BULL and (upside is None or upside > 0):
            final += note("analyst_bull", caps["analyst"], f"+{caps['analyst']:.0f} analysts bullish")

    # ---- Earnings gap guard (demote NEW entries near a print) ----
    days = (earnings or {}).get("days_until")
    if days is not None and days <= thresholds.get("earnings_window_days", 5):
        final += note("earnings_soon", -caps["earnings_soon"], f"-{caps['earnings_soon']:.0f} earnings in {days}d")

    # ---- SEC EDGAR filings (primary-source catalysts + activist stakes) ----
    # Additive caps use .get() defaults so an older adjudicator.yaml (predating these
    # sources) keeps working — same forgiving style as the thresholds above.
    if edgar:
        if edgar.get("severe"):
            sev = caps.get("risk_high", 20)
            final += note("edgar_severe", -sev, f"-{sev:.0f} SEC: {edgar.get('severe_reason') or 'severe filing'}")
        if edgar.get("catalyst"):
            cap = caps.get("edgar_catalyst", 15)
            kinds = ", ".join(edgar.get("catalyst_types") or []) or "8-K"
            final += note("edgar_catalyst", cap, f"+{cap:.0f} SEC 8-K ({kinds})")
        elif edgar.get("negative"):
            cap = caps.get("edgar_catalyst", 15)
            final += note("edgar_adverse", -cap, f"-{cap:.0f} SEC 8-K (adverse)")
        if edgar.get("activist"):
            cap = caps.get("activist_stake", 12)
            final += note("activist_stake", cap, f"+{cap:.0f} activist 13D stake")

    # ---- Options flow (free yfinance chains; only when volume is real & unusual) ----
    if options:
        total_vol = (options.get("call_volume") or 0) + (options.get("put_volume") or 0)
        unusual = (options.get("vol_oi_ratio") or 0) >= thresholds.get("options_unusual_ratio", 0.5)
        if total_vol >= thresholds.get("options_min_volume", 1000) and unusual:
            cap = caps.get("options_flow", 8)
            if options.get("direction") == "bullish":
                final += note("options_bull", cap, f"+{cap:.0f} unusual call flow")
            elif options.get("direction") == "bearish":
                final += note("options_bear", -cap, f"-{cap:.0f} unusual put flow")

    # ---- Short interest: squeeze setup (corroborated) vs crowded short (weak chart) ----
    # `fresh` (default True) drops a squeeze/crowded call when the exchange short-interest
    # report is stale — yfinance .info can lag weeks, and the number moves markets only fresh.
    if short and short.get("fresh", True) and short.get("pct_float") is not None \
            and short["pct_float"] >= thresholds.get("short_high_pct", 20):
        cap = caps.get("short_squeeze", 10)
        wsb_rising = bool(wsb and (wsb.get("mentions_change") or 0) > 0)
        if base >= 60 or wsb_rising:
            final += note("squeeze_setup", cap, f"+{cap:.0f} squeeze setup ({short['pct_float']:.0f}% short)")
        else:
            final += note("crowded_short", -cap, f"-{cap:.0f} crowded short ({short['pct_float']:.0f}% short)")

    # ---- Analyst estimate-revision momentum (drift beats a static rating) ----
    if revision:
        cap = caps.get("estimate_revision", 5)
        if revision.get("revision_trend") == "up":
            final += note("estimates_up", cap, f"+{cap:.0f} estimates rising")
        elif revision.get("revision_trend") == "down":
            final += note("estimates_down", -cap, f"-{cap:.0f} estimates falling")

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
            detail.append({"key": "wsb_contrarian", "points": round(-applied, 2)})
        elif rising and applied:
            final += applied
            social_summary = f"+{applied:g} WSB buzz (trust {social_trust:.0%})"
            detail.append({"key": "wsb_buzz", "points": round(applied, 2)})
        if social_summary:
            adjustments.append(social_summary)

    # Recompute the final score from the structured detail so the positive stack is capped.
    # (Every adjustment — including the social block above — is recorded in `detail`; nothing
    # mid-function reads the running `final`, which keys off `base`.) Positives saturate;
    # negatives apply in full.
    pos = sum(d["points"] for d in detail if d["points"] > 0)
    neg = sum(d["points"] for d in detail if d["points"] < 0)
    # `rank_score` is UNCAPPED — it's what the shortlist is sorted by, so a dozen names that
    # all clamp to a displayed 100 still separate (and a negative like put flow / falling
    # estimates actually pushes a name DOWN the ranking instead of vanishing under the clamp).
    # `final_score` is the same value clamped to 0-100 — the number the reader sees.
    rank = base + _soft_cap_positive(pos) + neg
    final = max(0.0, min(100.0, rank))

    return {
        "ticker": ticker, "base_score": base, "final_score": final, "rank_score": rank,
        "vetoed": False, "veto_reason": "",
        "news": news, "risk": risk, "regime": regime, "adjustments": adjustments,
        "adjustment_detail": detail,
        "congress": congress, "social": social_summary, "social_trust": social_trust,
        "analyst": analyst, "insider": insider, "earnings": earnings,
        "edgar": edgar, "options": options, "short": short, "revision": revision,
    }
