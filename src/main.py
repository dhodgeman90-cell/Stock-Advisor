import datetime as dt
import os
from pathlib import Path

import pandas as pd

from src import (config, data, scoring, news, agents, adjudicator, briefing,
                 exits, broker, social, congress, insights, market, rotation)

ROOT = Path(__file__).resolve().parent.parent

MAX_ADDS = 3   # most names the daily rotation will recommend buying into


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


def run(force: bool = False) -> str:
    # Make console output crash-proof: the briefing contains emojis that the
    # legacy Windows console (cp1252) cannot encode. UTF-8 + replace avoids a
    # UnicodeEncodeError without affecting the UTF-8 file that's saved.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # The market is closed on weekends and holidays, so a briefing then is just
    # wasted API tokens and an email the owner can't act on. Bail out before any
    # work. Run anyway with `python -m src.main --force` to test on a closed day.
    if _should_skip_today(dt.date.today(), force):
        msg = "Market closed today (weekend/holiday); skipping briefing (use --force to override)."
        print(msg)
        return msg

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    wl = config.load_watchlist()
    weights = config.load_weights()
    caps = config.load_adjudicator()
    signals_cfg = config.load_signals()
    thr = signals_cfg["thresholds"]
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)
    shortlist_size = settings.get("shortlist_size", 8)

    data_dir = ROOT / "data"
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = dt.date.today().isoformat()

    scored = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, lookback)
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

    # ---- Phase 3: evaluate exit signals on current holdings ----
    positions = broker.resolve_positions(
        on_error=lambda e: print(f"[holdings: SnapTrade sync failed, using positions.yaml: {e}]")
    )
    exit_rules = config.load_exit_rules()
    df_by_ticker = {s["ticker"]: s.get("_df") for s in scored if s.get("_df") is not None}

    holdings = []
    for pos in positions:
        df = df_by_ticker.get(pos["ticker"])
        ok = df is not None
        if df is None:
            df = data.fetch_history(pos["ticker"], lookback)
            ok, _ = data.validate(df, pos["ticker"])
            if ok:
                data.save_cache(df, pos["ticker"], data_dir)
            else:
                df = data.load_cache(pos["ticker"], data_dir)
                ok = df is not None and data.validate(df, pos["ticker"])[0]
        if not ok:
            holdings.append({
                "ticker": pos["ticker"], "current_price": float("nan"),
                "pct_from_entry": 0.0, "signals": [],
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

    # ---- New signal sources: fetch the market-wide feeds once (all fall back gracefully) ----
    wsb_map = social.get_wsb_sentiment()
    congress_trades = congress.get_congress_trades()
    congress_agg = congress.aggregate_by_ticker(congress_trades)
    breadth = market.get_market_breadth()

    # Attach smart-money signals to holdings so the rotation can spot insiders/congress leaving.
    for h in holdings:
        h["congress"] = congress_agg.get(h["ticker"])
        h["insider"] = insights.get_insider_signal(h["ticker"])

    known = set(wl["tickers"]) | {h["ticker"] for h in holdings}
    discovery = _discovery_feed(congress_trades, wsb_map, known, signals_cfg)

    has_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    client = None
    if has_llm:
        from src import llm
        client = llm.AnthropicClient()

    # Market regime: the LLM strategist when available, otherwise the deterministic
    # VIX/breadth read so the free-tier brief still gets a real regime call.
    if has_llm:
        summary = _build_market_summary(scored) + " " + breadth["regime_hint"]
        context = agents.context_agent(client, summary)
    else:
        context = {"regime": breadth["regime"], "note": breadth["regime_hint"]}

    cands = sorted((s for s in scored if not s["excluded"]),
                   key=lambda s: s["score"], reverse=True)
    shortlist = cands[:shortlist_size]
    others = [{"ticker": s["ticker"], "score": s["score"]} for s in cands[shortlist_size:]]
    excluded = [{"ticker": s["ticker"], "reason": s["reason"]}
                for s in scored if s["excluded"]]

    ranked, vetoed = [], []
    for s in shortlist:
        ticker = s["ticker"]
        wsb_sig = wsb_map.get(ticker)
        congress_sig = congress_agg.get(ticker)
        analyst_sig = insights.get_analyst_signal(ticker)
        insider_sig = insights.get_insider_signal(ticker)
        earnings_sig = insights.get_earnings(ticker)

        if has_llm:
            headlines = news.get_headlines(ticker)
            recent_closes = list(s["_df"]["Close"].tail(10))
            nv = agents.news_agent(client, ticker, headlines)
            rv = agents.risk_agent(client, ticker, recent_closes, headlines)
            # ApeWisdom gives counts, not post text, so we hand the agent a one-line
            # summary of the buzz; a velocity spike with no news reads as hype.
            if wsb_sig and (wsb_sig.get("mentions") or 0) >= thr["social_min_mentions"]:
                chatter = [f"{wsb_sig['mentions']} WSB mentions, "
                           f"{wsb_sig.get('mentions_change')} change in 24h, rank {wsb_sig.get('rank')}"]
                sv = agents.social_agent(client, ticker, chatter)
            else:
                sv = dict(agents.NEUTRAL_SOCIAL)
        else:
            nv, rv = dict(agents.NEUTRAL_NEWS), dict(agents.NEUTRAL_RISK)
            sv = dict(agents.NEUTRAL_SOCIAL)

        adjd = adjudicator.adjudicate(
            {"ticker": ticker, "score": s["score"]}, nv, rv, context, caps,
            congress=congress_sig, wsb=wsb_sig, social_view=sv,
            analyst=analyst_sig, insider=insider_sig, earnings=earnings_sig, thresholds=thr,
        )
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    ranked.sort(key=lambda r: r["final_score"], reverse=True)

    # Optional: annotate held names with the Risk agent (annotates only; never drives exits)
    if has_llm:
        for h in holdings:
            try:
                df_h = df_by_ticker.get(h["ticker"])
                recent = list(df_h["Close"].tail(10)) if df_h is not None else []
                rv = agents.risk_agent(client, h["ticker"], recent, news.get_headlines(h["ticker"]))
                if rv.get("veto") or rv.get("risk_level") == "high":
                    h["risk_flag"] = rv.get("reason") or "elevated risk"
            except Exception:
                pass   # annotation is best-effort; never break the briefing

    rotation_plan = rotation.build_rotation_plan(
        holdings, ranked, conviction=exit_rules["backtest"]["buy_threshold"], max_adds=MAX_ADDS,
    )

    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"],
        holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
    )
    (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
    print(text)
    if not has_llm:
        print("\n[AI agents disabled: no ANTHROPIC_API_KEY — running on deterministic signals only]")

    # Optional email
    if all(os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            html_body = briefing.render_briefing_html(
                ranked, vetoed, others, excluded, date_str,
                context["regime"], context["note"],
                holdings=holdings, rotation_plan=rotation_plan, discovery=discovery,
            )
            briefing.send_email(
                f"Stock Advisor — {date_str}", text,
                host=os.environ.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(os.environ.get("EMAIL_PORT", "465")),
                user=os.environ["EMAIL_USER"],
                password=os.environ["EMAIL_PASSWORD"],
                to_addr=os.environ["EMAIL_TO"],
                html_body=html_body,
            )
            print("[briefing emailed]")
        except Exception as e:
            print(f"[email failed: {e}]")

    return text


if __name__ == "__main__":
    import sys
    run(force="--force" in sys.argv[1:])
