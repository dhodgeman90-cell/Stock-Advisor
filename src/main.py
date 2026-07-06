import datetime as dt
import os
from pathlib import Path

import pandas as pd

from src import (config, data, scoring, news, agents, adjudicator, briefing,
                 exits, broker, social, congress, insights, market, rotation,
                 objectives, onboarding, edgar, options, fetchpool, picks, scorecard)
from src.profile import Profile
from src.results import RunResult

ROOT = Path(__file__).resolve().parent.parent

MAX_ADDS = 3   # most names the daily rotation will recommend buying into
ENRICH_TIMEOUT_S = 45   # per-ticker ceiling for the parallel signal enrichment (secondary
                        # bound; data.fetch_history's network timeout is the real hang guard)


def _should_skip_today(today: dt.date, force: bool = False) -> bool:
    """True when the NYSE has no session today (weekend OR market holiday), so we
    don't spend API tokens or email a briefing the owner can't act on. `force`
    (the --force flag) overrides it for manual testing.

    Uses the bundled NYSE calendar; if that import ever fails we fall back to a
    weekend-only check so the weekend protection still holds. Half-days (e.g. the
    day after Thanksgiving) DO have a session, so they correctly run.
    """
    if force:
        return False
    try:
        import pandas_market_calendars as mcal
        schedule = mcal.get_calendar("NYSE").schedule(start_date=today, end_date=today)
        return schedule.empty
    except Exception:
        return today.weekday() >= 5


def _build_market_summary(scored: list) -> str:
    cands = [s for s in scored if not s["excluded"]]
    if not cands:
        return "No qualifying stocks today."
    avg = sum(s["score"] for s in cands) / len(cands)
    up = sum(1 for s in cands if s["components"]["trend"] >= 1.0)
    return (f"{up}/{len(cands)} watchlist names in a clear uptrend; "
            f"average momentum score {avg:.0f}/100.")


def _discovery_feed(congress_trades, wsb_map, known_tickers, signals_cfg, today=None) -> dict:
    """Surface actionable signals on names the owner does NOT already hold or track.

    Congress side: large, recently-disclosed trades. WSB side: names with real mention
    volume that are climbing. Both exclude known tickers (those already appear in the
    main briefing) and are capped at the configured top_n.
    """
    thr = signals_cfg["thresholds"]
    disc = signals_cfg["discovery"]
    known = {str(t).upper() for t in known_tickers}

    big = congress.recent_large_trades(
        congress_trades, min_amount=thr["congress_large_usd"],
        lookback_days=disc["congress_lookback_days"], today=today,
    )
    congress_movers = [t for t in big if t["ticker"] not in known][:disc["top_n"]]

    wsb_movers = []
    for ticker, sig in sorted(wsb_map.items(),
                              key=lambda kv: (kv[1].get("mentions_change") or 0), reverse=True):
        if ticker in known or (sig.get("mentions") or 0) < thr["social_min_mentions"]:
            continue
        if (sig.get("mentions_change") or 0) <= 0:
            continue
        wsb_movers.append({"ticker": ticker, "mentions": sig["mentions"],
                           "mentions_change": sig.get("mentions_change")})
        if len(wsb_movers) >= disc["top_n"]:
            break
    return {"congress": congress_movers, "wsb": wsb_movers}


def _neutral_bundle() -> dict:
    """No-opinion per-candidate signal bundle (used if a ticker's enrichment fails)."""
    return {
        "analyst": dict(insights.NEUTRAL_ANALYST),
        "insider": dict(insights.NEUTRAL_INSIDER),
        "earnings": dict(insights.NEUTRAL_EARNINGS),
        "short": dict(insights.NEUTRAL_SHORT),
        "revision": dict(insights.NEUTRAL_REVISION),
        "edgar": dict(edgar.NEUTRAL_SEC),
        "options": dict(options.NEUTRAL_OPTIONS),
    }


def _enrich_candidate(ticker, cik_map, sec_window) -> dict:
    """All per-ticker deterministic signals for one candidate (each degrades on its own).

    Run once per shortlisted ticker, in parallel across tickers (see fetchpool) so the
    several network round-trips overlap rather than stack up serially.
    """
    return {
        "analyst": insights.get_analyst_signal(ticker),
        "insider": insights.get_insider_signal(ticker),
        "earnings": insights.get_earnings(ticker),
        "short": insights.get_short_signal(ticker),
        "revision": insights.get_revision_signal(ticker),
        "edgar": edgar.get_sec_signal(ticker, cik_map, window_days=sec_window),
        "options": options.get_options_signal(ticker),
    }


def _projected_score(base_score, context, caps, *, congress=None, wsb=None,
                     analyst=None, insider=None, earnings=None, thresholds=None,
                     edgar=None, options=None, short=None, revision=None) -> float:
    """Adjudicated score using ONLY the signals known WITHOUT AI: the base score plus the
    deterministic congress/insider/analyst/earnings/wsb boosts (AI news/risk/social are
    fed in NEUTRAL). This is what decides whether a candidate is shaping up as a buy and
    is therefore worth spending Claude tokens on. Gating on the raw base score alone (the
    old behaviour) skipped AI for names that clear the bar via those deterministic
    boosts — exactly the candidates the briefing then recommends.

    Known limitation: the projection uses the deterministic regime; the AI context_agent
    can flip the regime by ±caps["regime"] in the final adjudication. So a name projecting
    within caps["regime"] just below buy_threshold can still cross the bar in the final
    score yet be labelled rules-only. The deterministic boosts (+8..+18) dwarf that ±5
    wobble, so this is an accepted edge for now rather than widening AI spend near the bar.
    """
    proj = adjudicator.adjudicate(
        {"ticker": "_", "score": base_score},
        dict(agents.NEUTRAL_NEWS), dict(agents.NEUTRAL_RISK), context, caps,
        congress=congress, wsb=wsb, social_view=dict(agents.NEUTRAL_SOCIAL),
        analyst=analyst, insider=insider, earnings=earnings, thresholds=thresholds,
        edgar=edgar, options=options, short=short, revision=revision,
    )
    return proj["final_score"]


def _ai_is_actionable(holdings, projected_scores, buy_threshold) -> bool:
    """Whether today warrants spending Claude tokens.

    True when a holding is already flagging a deterministic exit signal, or any candidate
    already PROJECTS as a buy on signals known without AI (`projected_scores` = adjudicated
    scores using neutral AI views; see `_projected_score`). On a quiet day (neither) the
    per-ticker LLM calls are skipped in favour of the deterministic views, so the owner
    isn't paying Haiku to rubber-stamp 'hold'.
    """
    if any(h.get("signals") for h in holdings):
        return True
    return any(score >= buy_threshold for score in projected_scores)


def run(profile: Profile | None = None, force: bool = False, *, fetch=None) -> RunResult:
    # Make console output crash-proof: the briefing contains emojis that the legacy
    # Windows console (cp1252) cannot encode. UTF-8 + replace avoids a crash without
    # affecting the UTF-8 file that's saved.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if profile is None:
        profile = Profile.for_repo()
    profile.ensure_dirs()
    secrets = profile.secrets
    secrets.apply_to_environ()          # legacy modules (broker/llm/congress) read os.environ
    if fetch is None:
        fetch = data.fetch_history

    date_str = dt.date.today().isoformat()

    # Market closed on weekends/holidays -> no actionable briefing. `--force` overrides.
    if _should_skip_today(dt.date.today(), force):
        msg = "Market closed today (weekend/holiday); skipping briefing (use --force to override)."
        print(msg)
        return RunResult(date=date_str, text=msg, skipped=True)

    objective = onboarding.get_objective(profile)
    wl = config.load_watchlist(profile.config_dir)
    weights = objectives.apply_weights(config.load_weights(profile.config_dir), objective)
    caps = config.load_adjudicator(profile.config_dir)
    signals_cfg = config.load_signals(profile.config_dir)
    thr = signals_cfg["thresholds"]
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)
    shortlist_size = settings.get("shortlist_size", 8)

    data_dir = profile.data_dir
    reports_dir = profile.reports_dir

    scored = []
    for ticker in wl["tickers"]:
        df = fetch(ticker, lookback)
        ok, reason = data.validate(df, ticker)
        if ok:
            data.save_cache(df, ticker, data_dir)
        else:
            df = data.load_cache(ticker, data_dir)
            cache_ok, _ = data.validate(df, ticker) if df is not None else (False, "")
            if not cache_ok:
                scored.append({"ticker": ticker, "excluded": True,
                               "reason": f"{reason} (no valid cache)"})
                continue
        result = scoring.score_ticker(df, ticker, weights, settings)
        result["_df"] = df if not result["excluded"] else None
        scored.append(result)

    # ---- evaluate exit signals on current holdings ----
    positions = broker.resolve_positions(
        load_positions=lambda: config.load_positions(profile.config_dir),
        load_overrides=lambda: config.load_position_overrides(profile.config_dir),
        on_error=lambda e: print(f"[holdings: SnapTrade sync failed, using positions.yaml: {e}]"),
    )
    exit_rules = objectives.apply_exit_rules(config.load_exit_rules(profile.config_dir), objective)
    df_by_ticker = {s["ticker"]: s.get("_df") for s in scored if s.get("_df") is not None}

    holdings = []
    for pos in positions:
        df = df_by_ticker.get(pos["ticker"])
        ok = df is not None
        if df is None:
            df = fetch(pos["ticker"], lookback)
            ok, reason = data.validate(df, pos["ticker"])
            if ok:
                data.save_cache(df, pos["ticker"], data_dir)
            else:
                cached = data.load_cache(pos["ticker"], data_dir)
                cache_ok, cache_reason = (data.validate(cached, pos["ticker"])
                                          if cached is not None else (False, "no cache"))
                df, ok = cached, cache_ok
                if not ok:
                    # Surface the failure instead of silently emitting a green "hold".
                    print(f"[holdings: {pos['ticker']} price unavailable — "
                          f"fresh: {reason}; cache: {cache_reason}]")
        if not ok:
            holdings.append({
                "ticker": pos["ticker"], "current_price": float("nan"),
                "pct_from_entry": 0.0, "signals": [], "as_of": None,
                "risk_flag": "no valid price data",
            })
            continue
        entry_date = pos.get("entry_date") or ""
        try:
            if entry_date:
                since = df.loc[df.index >= pd.Timestamp(entry_date)]
                peak = float(since["Close"].max()) if len(since) else float(pos["entry_price"])
            else:
                peak = float(pos["entry_price"])
        except Exception:
            peak = float(pos["entry_price"])
        holdings.append(exits.evaluate_exit(df, {**pos, "peak_price": peak}, exit_rules))

    # ---- market-wide feeds (each falls back gracefully) ----
    wsb_map = social.get_wsb_sentiment(cache_path=profile.data_dir / "wsb_sentiment.json")
    congress_trades = congress.get_congress_trades(cache_path=profile.data_dir / "congress_trades.json")
    congress_agg = congress.aggregate_by_ticker(congress_trades)
    breadth = market.get_market_breadth()
    macro = market.get_macro_context()
    # SEC ticker->CIK map: fetched once (cached) and shared across all per-candidate lookups.
    cik_map = edgar.load_cik_map(cache_path=profile.data_dir / "sec_cik_map.json")
    sec_window = thr.get("sec_window_days", 30)

    for h in holdings:
        h["congress"] = congress_agg.get(h["ticker"])
        h["insider"] = insights.get_insider_signal(h["ticker"])

    known = set(wl["tickers"]) | {h["ticker"] for h in holdings}
    discovery = _discovery_feed(congress_trades, wsb_map, known, signals_cfg)

    cands = sorted((s for s in scored if not s["excluded"]),
                   key=lambda s: s["score"], reverse=True)
    shortlist = cands[:shortlist_size]
    others = [{"ticker": s["ticker"], "score": s["score"]} for s in cands[shortlist_size:]]
    excluded = [{"ticker": s["ticker"], "reason": s["reason"]}
                for s in scored if s["excluded"]]

    # Spend Claude tokens only where it matters. A candidate is worth AI only if it already
    # PROJECTS as a buy on the signals known WITHOUT AI (base score + deterministic
    # congress/insider/analyst/earnings/wsb boosts). Gating on the raw base score alone
    # used to skip AI for names that become buys via those boosts — the exact candidates
    # the briefing recommends — leaving them labelled "news agent unavailable".
    buy_threshold = exit_rules["backtest"]["buy_threshold"]
    # Macro overlay is worst-of with breadth: an inverted curve / stressed credit can pull
    # an otherwise-calm tape to risk_off. Both hints are shown so the regime is explainable.
    combined_regime = ("risk_off" if "risk_off" in (breadth["regime"], macro["macro_regime"])
                       else breadth["regime"])
    regime_note = f'{breadth["regime_hint"]} {macro["macro_hint"]}'.strip()
    det_context = {"regime": combined_regime, "note": regime_note}

    # Per-candidate deterministic signals, fetched in PARALLEL (each network call is
    # I/O-bound; fetchpool overlaps them so the run stays inside the time budget), then a
    # neutral-AI projection (pure; spends no tokens).
    enriched = fetchpool.fetch_map(
        [s["ticker"] for s in shortlist],
        lambda t: _enrich_candidate(t, cik_map, sec_window),
        default=_neutral_bundle,
        timeout=ENRICH_TIMEOUT_S,
    )
    cand_rows = []   # (scored_row, signals, projected_score)
    for s in shortlist:
        ticker = s["ticker"]
        e = enriched.get(ticker) or _neutral_bundle()
        sigs = {
            "congress": congress_agg.get(ticker),
            "wsb": wsb_map.get(ticker),
            "analyst": e["analyst"], "insider": e["insider"], "earnings": e["earnings"],
            "short": e["short"], "revision": e["revision"],
            "edgar": e["edgar"], "options": e["options"],
        }
        projected = _projected_score(
            s["score"], det_context, caps,
            congress=sigs["congress"], wsb=sigs["wsb"], analyst=sigs["analyst"],
            insider=sigs["insider"], earnings=sigs["earnings"], thresholds=thr,
            edgar=sigs["edgar"], options=sigs["options"], short=sigs["short"],
            revision=sigs["revision"],
        )
        cand_rows.append((s, sigs, projected))

    holdings_actionable = any(h.get("signals") for h in holdings)
    has_llm = bool(secrets.get("ANTHROPIC_API_KEY"))
    use_ai = has_llm and _ai_is_actionable(
        holdings, [p for _, _, p in cand_rows], buy_threshold)

    client = None
    if use_ai:
        from src import llm
        client = llm.AnthropicClient()

    if use_ai:
        summary = _build_market_summary(scored) + " " + regime_note
        context = agents.context_agent(client, summary)
    else:
        context = det_context

    ranked, vetoed = [], []
    for s, sigs, projected in cand_rows:
        ticker = s["ticker"]
        congress_sig, wsb_sig = sigs["congress"], sigs["wsb"]
        analyst_sig, insider_sig, earnings_sig = sigs["analyst"], sigs["insider"], sigs["earnings"]

        if use_ai and projected >= buy_threshold:
            headlines = news.get_headlines(ticker)
            recent_closes = list(s["_df"]["Close"].tail(10))
            nv = agents.news_agent(client, ticker, headlines)
            rv = agents.risk_agent(client, ticker, recent_closes, headlines)
            if wsb_sig and (wsb_sig.get("mentions") or 0) >= thr["social_min_mentions"]:
                chatter = [f"{wsb_sig['mentions']} WSB mentions, "
                           f"{wsb_sig.get('mentions_change')} change in 24h, rank {wsb_sig.get('rank')}"]
                sv = agents.social_agent(client, ticker, chatter)
            else:
                sv = dict(agents.NEUTRAL_SOCIAL)
        else:
            # Intentional skip (rules-only mode, or not projecting as a buy) — honest label,
            # distinct from a genuine agent failure (NEUTRAL_*). Same scoring effect.
            nv, rv = dict(agents.SKIPPED_NEWS), dict(agents.SKIPPED_RISK)
            sv = dict(agents.NEUTRAL_SOCIAL)

        adjd = adjudicator.adjudicate(
            {"ticker": ticker, "score": s["score"]}, nv, rv, context, caps,
            congress=congress_sig, wsb=wsb_sig, social_view=sv,
            analyst=analyst_sig, insider=insider_sig, earnings=earnings_sig, thresholds=thr,
            edgar=sigs["edgar"], options=sigs["options"], short=sigs["short"],
            revision=sigs["revision"],
        )
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    ranked.sort(key=lambda r: r["final_score"], reverse=True)

    # Log today's picks to the structured ledger so the scorecard can later grade how
    # they performed. Guarded like the email block — a ledger hiccup must never break the
    # briefing the owner is reading.
    try:
        picks.log_picks(ranked, df_by_ticker, profile.data_dir, date_str)
    except Exception as e:
        print(f"[pick log failed: {e}]")

    if use_ai and holdings_actionable:
        for h in holdings:
            if not h.get("signals"):
                continue   # only spend a risk call on holdings already flagging an exit
            try:
                df_h = df_by_ticker.get(h["ticker"])
                recent = list(df_h["Close"].tail(10)) if df_h is not None else []
                rv = agents.risk_agent(client, h["ticker"], recent, news.get_headlines(h["ticker"]))
                if rv.get("veto") or rv.get("risk_level") == "high":
                    h["risk_flag"] = rv.get("reason") or "elevated risk"
            except Exception:
                pass

    if has_llm and not use_ai:
        print("[AI agents skipped: no actionable buy/sell signals today — "
              "running on deterministic signals only]")

    rotation_plan = rotation.build_rotation_plan(
        holdings, ranked, conviction=exit_rules["backtest"]["buy_threshold"], max_adds=MAX_ADDS,
    )

    # Reality-check header: grade our OWN past picks vs SPY and put the number at the top of
    # the briefing. Reuse the histories already fetched this run (cache-first) so this adds
    # only a SPY pull, not a full refetch, and never let a scorecard hiccup break the email.
    def _sc_fetch(ticker, days):
        cached = df_by_ticker.get(ticker)
        return cached if cached is not None else fetch(ticker, days)

    scorecard_summary = None
    try:
        scorecard_summary = scorecard.briefing_summary(profile, fetch=_sc_fetch)
    except Exception as e:
        print(f"[scorecard summary failed: {e}]")

    tone = objectives.tone_line(objective)
    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
        scorecard_summary=scorecard_summary,
    )
    html = briefing.render_briefing_html(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
        scorecard_summary=scorecard_summary,
    )
    report_path = reports_dir / f"{date_str}.md"
    report_path.write_text(text, encoding="utf-8")
    print(text)
    if not has_llm:
        print("\n[AI agents disabled: no ANTHROPIC_API_KEY — running on deterministic signals only]")

    # Optional email (only when all EMAIL_* secrets are present)
    if all(secrets.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            briefing.send_email(
                f"Stock Advisor — {date_str}", text,
                host=secrets.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(secrets.get("EMAIL_PORT", "465")),
                user=secrets.get("EMAIL_USER"),
                password=secrets.get("EMAIL_PASSWORD"),
                to_addr=secrets.get("EMAIL_TO"),
                html_body=html,
            )
            print("[briefing emailed]")
        except Exception as e:
            print(f"[email failed: {e}]")

    return RunResult(
        date=date_str, text=text, html=html,
        regime=context["regime"], regime_note=context["note"],
        ranked=ranked, vetoed=vetoed, others=others, excluded=excluded,
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
        report_path=report_path, skipped=False,
    )


if __name__ == "__main__":
    import sys
    run(force="--force" in sys.argv[1:])
