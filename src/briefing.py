from email.message import EmailMessage


def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note) -> str:
    """Render the enriched daily briefing (Phase 2). `ranked` is pre-sorted by final_score."""
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
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
