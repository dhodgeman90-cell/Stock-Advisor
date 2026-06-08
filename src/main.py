import datetime as dt
import os
from pathlib import Path

from src import config, data, scoring, news, agents, adjudicator, briefing, report

ROOT = Path(__file__).resolve().parent.parent


def _build_market_summary(scored: list) -> str:
    cands = [s for s in scored if not s["excluded"]]
    if not cands:
        return "No qualifying stocks today."
    avg = sum(s["score"] for s in cands) / len(cands)
    up = sum(1 for s in cands if s["components"]["trend"] >= 1.0)
    return (f"{up}/{len(cands)} watchlist names in a clear uptrend; "
            f"average momentum score {avg:.0f}/100.")


def run() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    wl = config.load_watchlist()
    weights = config.load_weights()
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

    # Graceful fallback: no API key -> deterministic-only report (Phase 1 behavior)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        clean = [{k: v for k, v in s.items() if k != "_df"} for s in scored]
        text = report.render_report(clean, date_str)
        (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
        print(text)
        print("\n[AI agents disabled: no ANTHROPIC_API_KEY in .env]")
        return text

    from src import llm
    client = llm.AnthropicClient()
    caps = config.load_adjudicator()

    cands = sorted((s for s in scored if not s["excluded"]),
                   key=lambda s: s["score"], reverse=True)
    shortlist = cands[:shortlist_size]
    others = [{"ticker": s["ticker"], "score": s["score"]} for s in cands[shortlist_size:]]
    excluded = [{"ticker": s["ticker"], "reason": s["reason"]}
                for s in scored if s["excluded"]]

    context = agents.context_agent(client, _build_market_summary(scored))

    ranked, vetoed = [], []
    for s in shortlist:
        headlines = news.get_headlines(s["ticker"])
        recent_closes = list(s["_df"]["Close"].tail(10))
        nv = agents.news_agent(client, s["ticker"], headlines)
        rv = agents.risk_agent(client, s["ticker"], recent_closes, headlines)
        adjd = adjudicator.adjudicate(
            {"ticker": s["ticker"], "score": s["score"]}, nv, rv, context, caps
        )
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    ranked.sort(key=lambda r: r["final_score"], reverse=True)

    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"]
    )
    (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
    print(text)

    # Optional email
    if all(os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            briefing.send_email(
                f"Stock Advisor — {date_str}", text,
                host=os.environ.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(os.environ.get("EMAIL_PORT", "465")),
                user=os.environ["EMAIL_USER"],
                password=os.environ["EMAIL_PASSWORD"],
                to_addr=os.environ["EMAIL_TO"],
            )
            print("[briefing emailed]")
        except Exception as e:
            print(f"[email failed: {e}]")

    return text


if __name__ == "__main__":
    run()
