from email.message import EmailMessage


def render_holdings_section(holdings) -> str:
    """Markdown block for current holdings + their exit signals. Leads the briefing."""
    lines = ["## 📊 Your holdings"]
    if not holdings:
        lines.append("_No tracked positions. Keep `positions.yaml` current as you buy and sell._")
        return "\n".join(lines)
    for h in holdings:
        lines.append(
            f"- **{h['ticker']}**: ${h['current_price']:.2f} "
            f"({h['pct_from_entry']:+.1f}% from entry)"
        )
        if h["signals"]:
            for s in h["signals"]:
                lines.append(f"    - {s['emoji']} {s['type'].replace('_', ' ')}: {s['detail']}")
        else:
            lines.append("    - 🟢 holding — no exit signal")
        if h.get("risk_flag"):
            lines.append(f"    - ⚠️ {h['risk_flag']}")
    lines.append("")
    lines.append("_Reminder: keep `positions.yaml` current as you buy and sell._")
    return "\n".join(lines)


def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note,
                    holdings=None) -> str:
    """Render the enriched daily briefing (Phase 2 + Phase 3 holdings).

    `ranked` is pre-sorted by final_score. `holdings` (Phase 3) leads the briefing.
    """
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
        "",
        render_holdings_section(holdings),
        "",
        "## Top candidates",
    ]
    if not ranked:
        L.append("_No candidates today._")
    for r in ranked:
        adj = "  ".join(r["adjustments"]) or "no adjustments"
        L.append(f"- **{r['ticker']}**: {r['final_score']:.0f}/100 (base {r['base_score']:.0f})")
        L.append(f"    - 📰 {r['news']['summary']}")
        L.append(f"    - 🚩 risk {r['risk']['risk_level']}: {r['risk']['reason']}")
        L.append(f"    - adj: {adj}")

    if vetoed:
        L.append("")
        L.append("## ⛔ Vetoed (do not buy)")
        for r in vetoed:
            L.append(f"- {r['ticker']}: {r['veto_reason']}")

    if others:
        L.append("")
        L.append("## Other scored (below shortlist)")
        for o in others:
            L.append(f"- {o['ticker']}: {o['score']:.0f}/100")

    if excluded:
        L.append("")
        L.append("## Excluded (hard filters)")
        for e in excluded:
            L.append(f"- {e['ticker']}: {e['reason']}")

    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"


def send_email(subject, body, *, host, port, user, password, to_addr, smtp_factory=None) -> None:
    """Send the briefing via SMTP. `smtp_factory` is injectable for testing."""
    if smtp_factory is None:
        import smtplib

        def smtp_factory():
            return smtplib.SMTP_SSL(host, port)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    with smtp_factory() as server:
        server.login(user, password)
        server.send_message(msg)
