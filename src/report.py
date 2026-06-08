def render_report(scored: list[dict], date_str: str) -> str:
    """Render scored tickers into a ranked markdown report (Phase 1 — no AI)."""
    lines = [f"# Stock Advisor — {date_str}", ""]

    ranked = sorted(
        (s for s in scored if not s["excluded"]),
        key=lambda s: s["score"],
        reverse=True,
    )

    lines.append("## Candidates (ranked)")
    if not ranked:
        lines.append("_No candidates passed the filters today._")
    for s in ranked:
        c = s["components"]
        lines.append(
            f"- **{s['ticker']}**: {s['score']:.0f}/100  "
            f"[trend {c['trend']:.2f} · breakout {c['breakout']:.2f} · "
            f"volume {c['volume']:.2f} · rsi {c['momentum']:.2f}]"
        )

    excluded = [s for s in scored if s["excluded"]]
    if excluded:
        lines.append("")
        lines.append("## Excluded (hard filters)")
        for s in excluded:
            lines.append(f"- {s['ticker']}: {s['reason']}")

    lines.append("")
    lines.append("_Information only — not financial advice._")
    return "\n".join(lines) + "\n"
