import datetime as dt
import os
import random
from pathlib import Path

import pandas as pd

from src import (config, data, scoring, news, agents, adjudicator, briefing,
                 exits, broker, social, congress, insights, market, rotation,
                 objectives, onboarding, edgar, options, fetchpool, picks, scorecard,
                 signal_log)
from src.profile import Profile
from src.results import RunResult

ROOT = Path(__file__).resolve().parent.parent

MAX_ADDS = 3   # most names the daily rotation will recommend buying into
OTHERS_DISPLAY = 15   # cap the "other scored" / "excluded" lists so a wide universe doesn't
                      # dump hundreds of tickers into the briefing
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


def _count_live_signals(sigs) -> int:
    """How many of the 7 per-ticker enrichment signals returned a REAL (non-neutral) value.

    Every get_* degrades to its NEUTRAL_* sentinel on failure/missing data, so a momentum-only
    score can otherwise masquerade as fully enriched. A low count means "thin data" — the
    briefing flags it so a saturated score isn't mistaken for a well-corroborated one."""
    neutral = {
        "analyst": insights.NEUTRAL_ANALYST, "insider": insights.NEUTRAL_INSIDER,
        "earnings": insights.NEUTRAL_EARNINGS, "short": insights.NEUTRAL_SHORT,
        "revision": insights.NEUTRAL_REVISION, "edgar": edgar.NEUTRAL_SEC,
        "options": options.NEUTRAL_OPTIONS,
    }
    return sum(1 for k, n in neutral.items() if sigs.get(k) not in (None, n))


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


def _control_cohort(cands, exclude, size, date_str) -> list:
    """A deterministic random draw of eligible names to enrich purely for MEASUREMENT.

    The enriched shortlist is chosen by the legacy technical score, which measures a rank IC
    of ~0 but is emphatically not random: it selects names at 20-day highs on volume spikes.
    Capturing signal history only there means analyst/options/short-interest/EDGAR values are
    only ever observed on breakout names, so any signal correlated with breakout or volume
    comes back distorted. This draw is the unbiased comparison group that makes cross-sectional
    inference possible at all.

    Seeded on the date so a same-day rerun reproduces the same cohort — the briefing must stay
    reproducible. These names are logged and NEVER ranked, displayed, or recommended.
    """
    if size <= 0:
        return []
    pool = [s for s in cands if s["ticker"] not in exclude]
    if not pool:
        return []
    return random.Random(date_str).sample(pool, min(int(size), len(pool)))


def _has_priority_signal(ticker, congress_agg, wsb_map, min_mentions) -> bool:
    """True when a name carries a strong market-wide signal (fresh congressional buy or a
    surging WSB mention count) that warrants enrichment even if its chart ranked below the
    technical cut — so a catalyst on a middling chart isn't silently dropped before its
    fundamentals are ever evaluated (the old momentum-only enrichment gate)."""
    c = congress_agg.get(ticker)
    if c and c.get("fresh", True) and c.get("net_side") == "buy":
        return True
    w = wsb_map.get(ticker)
    if w and (w.get("mentions_change") or 0) > 0 and (w.get("mentions") or 0) >= min_mentions:
        return True
    return False


def _rs_reranked(ranked, df_by_ticker, spy_close):
    """Re-rank the shortlist by the relative-strength entry model (opt-in): cross-sectional RS
    percentile vs SPY blended with a constructive-pullback preference, replacing the
    breakout-chasing sort. Demotes fresh-high chasers within the shortlist — the inverted-top-band
    fix. Returns a new list, highest first."""
    rs_by = {r["ticker"]: scoring.relative_strength(df_by_ticker[r["ticker"]]["Close"], spy_close)
             for r in ranked if df_by_ticker.get(r["ticker"]) is not None}
    rs_pct = scoring.cross_sectional_rank(rs_by)

    def _val(r):
        df_r = df_by_ticker.get(r["ticker"])
        return (scoring.rs_entry_rank(df_r, rs_pct.get(r["ticker"], 0.5))
                if df_r is not None else -1.0)
    return sorted(ranked, key=_val, reverse=True)


def _confirmed_regime(spy_hist):
    """Today's confirmed market regime from SPY history: regime_series + hysteresis, last bar.
    'risk_on' on any error / short history — never go defensive without a clear, confirmed signal."""
    try:
        return market.apply_hysteresis(market.regime_series(spy_hist)).iloc[-1]
    except Exception:
        return "risk_on"


REGIME_MIN_DAYS = 400   # regime_series needs a 200-day MA; a 200-day universe lookback is only
                        # ~206 trading bars (MA valid on ~3), so size the SPY pull independently.


def _regime_fetch_days(lookback):
    """SPY history window for the regime/RS features: at least REGIME_MIN_DAYS so the 200-day MA
    (and the hysteresis on it) has enough valid bars, regardless of the universe lookback."""
    return max(lookback, REGIME_MIN_DAYS)


def run(profile: Profile | None = None, force: bool = False, *, fetch=None,
        fetch_batch=None) -> RunResult:
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
        if fetch_batch is None:
            fetch_batch = data.fetch_history_batch      # real bulk download in the live path
    if fetch_batch is None:
        # a test injected a per-ticker fetch but no batch — wrap it so the funnel still runs
        fetch_batch = lambda tickers, days: {t: fetch(t, days) for t in tickers}

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
    # Opt-in, default-off features (defaults keep the briefing byte-for-byte identical):
    entry_model = settings.get("entry_model", "legacy")            # "relative_strength" to enable
    regime_overlay = settings.get("regime_overlay", False)         # True = defensive in bear regimes
    adds_paused = settings.get("adds_paused", False)               # True = withhold BUY calls

    data_dir = profile.data_dir
    reports_dir = profile.reports_dir

    # Stage 1 of the funnel: score the whole universe cheaply from one bulk price download.
    # The universe is the broad scan list (config/universe.txt) if present, else the
    # watchlist; the watchlist names are always pinned in so the owner's picks never drop out.
    universe = config.load_universe(profile.config_dir) or wl["tickers"]
    universe = list(dict.fromkeys([*universe, *wl["tickers"]]))
    batch = fetch_batch(universe, lookback)

    scored = []
    for ticker in universe:
        df = batch.get(ticker)
        ok, reason = data.validate(df, ticker) if df is not None else (False, f"{ticker}: no data")
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
        data_dir=data_dir, today=date_str,
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
    # Stage 2: enrich the top `enrich_size` by technical score, PLUS any lower-ranked name
    # carrying a fresh congress-buy / WSB surge — so a catalyst on a middling chart still gets
    # its fundamentals evaluated instead of being cut by the momentum-only gate.
    enrich_size = settings.get("enrich_size", max(shortlist_size, 25))
    min_mentions = thr.get("social_min_mentions", 25)
    shortlist = list(cands[:enrich_size])
    enriched_names = {s["ticker"] for s in shortlist}
    for s in cands[enrich_size:]:
        if _has_priority_signal(s["ticker"], congress_agg, wsb_map, min_mentions):
            shortlist.append(s)
            enriched_names.add(s["ticker"])
    # Measurement-only draw. Enriched and logged like a candidate, but deliberately kept out of
    # `shortlist` so it can never be ranked, displayed, or recommended — see _control_cohort.
    control = _control_cohort(cands, enriched_names,
                              settings.get("control_cohort_size", 0), date_str)
    control_names = {s["ticker"] for s in control}
    others = [{"ticker": s["ticker"], "score": s["score"]}
              for s in cands
              if s["ticker"] not in enriched_names and s["ticker"] not in control_names]
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
        [s["ticker"] for s in shortlist] + [s["ticker"] for s in control],
        lambda t: _enrich_candidate(t, cik_map, sec_window),
        default=_neutral_bundle,
        timeout=ENRICH_TIMEOUT_S,
    )

    def _sig_bundle(ticker):
        e = enriched.get(ticker) or _neutral_bundle()
        return {
            "congress": congress_agg.get(ticker),
            "wsb": wsb_map.get(ticker),
            "analyst": e["analyst"], "insider": e["insider"], "earnings": e["earnings"],
            "short": e["short"], "revision": e["revision"],
            "edgar": e["edgar"], "options": e["options"],
        }

    cand_rows = []   # (scored_row, signals, projected_score)
    for s in shortlist:
        ticker = s["ticker"]
        sigs = _sig_bundle(ticker)
        projected = _projected_score(
            s["score"], det_context, caps,
            congress=sigs["congress"], wsb=sigs["wsb"], analyst=sigs["analyst"],
            insider=sigs["insider"], earnings=sigs["earnings"], thresholds=thr,
            edgar=sigs["edgar"], options=sigs["options"], short=sigs["short"],
            revision=sigs["revision"],
        )
        cand_rows.append((s, sigs, projected))

    # Point-in-time capture of every raw signal value, for the whole enriched shortlist (~25),
    # BEFORE any AI/adjudication narrows it. Analyst, options, short interest, WSB and congress
    # exist only as present-day snapshots — no free source sells their history — so this file is
    # the only way those signals will ever become backtestable. Guarded like the pick ledger:
    # a logging failure must never break the briefing.
    try:
        ctx = {"regime": combined_regime, "breadth": breadth.get("regime"),
               "macro": macro.get("macro_regime")}
        signal_log.log_signals(cand_rows, data_dir, date_str, context=ctx)
        # The unbiased comparison group. Without it the captured history only ever describes
        # breakout names, and no honest cross-sectional inference is possible from it.
        signal_log.log_signals([(s, _sig_bundle(s["ticker"]), None) for s in control],
                               data_dir, date_str, context=ctx, cohort="control")
    except Exception as e:
        print(f"[signal history log failed: {e}]")

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
        adjd["data_signals_live"] = _count_live_signals(sigs)
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    # Opt-in features need SPY history (regime signal + relative strength). Fetch once, only when
    # a feature is on, degrading to legacy behavior if it fails — the default run never fetches SPY
    # here and stays byte-identical.
    spy_hist = None
    if entry_model == "relative_strength" or regime_overlay:
        try:
            spy_hist = fetch("SPY", _regime_fetch_days(lookback))
        except Exception as e:
            print(f"[regime/RS features: SPY fetch failed, using legacy behavior: {e}]")
    if entry_model == "relative_strength" and spy_hist is not None:
        # Re-rank the shortlist by relative strength + constructive pullback (fixes the inverted
        # top band) instead of the breakout-tilted rank_score.
        ranked = _rs_reranked(ranked, df_by_ticker, spy_hist["Close"])
    else:
        # Sort by the UNCAPPED rank_score, not the clamped final_score: otherwise a dozen names
        # that all pin at a displayed 100 tie and fall back to arbitrary order, and negatives
        # (put flow, falling estimates) that push past the clamp become invisible to the ranking.
        ranked.sort(key=lambda r: r.get("rank_score", r["final_score"]), reverse=True)
    # Display cap: show only the top `shortlist_size` enriched candidates so the briefing stays
    # concise on a wide universe; the enriched-but-not-shown drop into "other scored".
    if len(ranked) > shortlist_size:
        overflow = [{"ticker": r["ticker"], "score": r["final_score"]}
                    for r in ranked[shortlist_size:]]
        ranked = ranked[:shortlist_size]
        others = sorted(overflow + others, key=lambda o: o["score"], reverse=True)

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

    # Defensive overlay (opt-in): in a CONFIRMED risk-off regime, recommend no new buys. Validated
    # as a DRAWDOWN reducer, NOT an index-beater (it loses to buy-and-hold in a bull market). Default
    # off -> max_adds unchanged, briefing byte-identical.
    effective_max_adds = MAX_ADDS
    if regime_overlay and spy_hist is not None and _confirmed_regime(spy_hist) == "risk_off":
        effective_max_adds = 0
        print("[defensive mode: confirmed risk-off regime — recommending no new buys "
              "(reduces drawdown; does NOT beat the index in a bull market)]")
    # Owner-set kill switch for the BUY side only. The ranking model has no measured edge
    # (live +1d alpha is negative at every score band, and the scorecard is ~40x too small to
    # detect a realistic one), so this withholds buy calls while keeping the sell side —
    # exits/trims on open positions — fully live. Candidates are still scored and displayed.
    if adds_paused:
        effective_max_adds = 0
        print("[adds paused: buy recommendations withheld pending validation — "
              "exit/trim advice on open positions is unaffected]")
    rotation_plan = rotation.build_rotation_plan(
        holdings, ranked, conviction=exit_rules["backtest"]["buy_threshold"],
        max_adds=effective_max_adds,
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

    others = others[:OTHERS_DISPLAY]
    excluded = excluded[:OTHERS_DISPLAY]
    tone = objectives.tone_line(objective)
    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
        scorecard_summary=scorecard_summary, buy_threshold=buy_threshold,
    )
    html = briefing.render_briefing_html(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery, tone_line=tone,
        scorecard_summary=scorecard_summary, buy_threshold=buy_threshold,
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
