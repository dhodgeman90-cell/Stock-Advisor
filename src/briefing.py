import html
import math
from email.message import EmailMessage


# Pill (background, foreground) colors for a holding signal level.
_PILL_COLORS = {
    "sell":  ("#fee2e2", "#991b1b"),   # red
    "trim":  ("#fef9c3", "#854d0e"),   # amber
    "watch": ("#fef9c3", "#854d0e"),   # amber
    "hold":  ("#dcfce7", "#166534"),   # green
}


def _signal_pill(level):
    """(background, foreground) hex colors for a holding signal level."""
    return _PILL_COLORS.get(level, _PILL_COLORS["hold"])


def render_holdings_section(holdings) -> str:
    """Markdown block for current holdings + their exit signals. Leads the briefing."""
    lines = ["## 📊 Your holdings"]
    if not holdings:
        lines.append("_No tracked positions. Keep `positions.yaml` current as you buy and sell._")
        return "\n".join(lines)
    for h in holdings:
        price = h["current_price"]
        if isinstance(price, float) and math.isnan(price):
            lines.append(f"- **{h['ticker']}**: price unavailable")
        else:
            lines.append(
                f"- **{h['ticker']}**: ${price:.2f} "
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


def _holdings_html(holdings, e) -> str:
    """HTML table of holdings with a color-coded signal pill per row."""
    if not holdings:
        return ('<div style="font-size:12.5px;color:#6b7280;">'
                'No tracked positions. Keep positions.yaml current as you buy and sell.</div>')
    rows = [
        '<tr style="color:#6b7280;text-align:left;">'
        '<th style="padding:7px 8px;border-bottom:2px solid #0f3d2e;font-weight:600;">Ticker</th>'
        '<th style="padding:7px 8px;border-bottom:2px solid #0f3d2e;font-weight:600;">Price</th>'
        '<th style="padding:7px 8px;border-bottom:2px solid #0f3d2e;font-weight:600;">vs entry</th>'
        '<th style="padding:7px 8px;border-bottom:2px solid #0f3d2e;font-weight:600;">Signal</th></tr>'
    ]
    for i, h in enumerate(holdings):
        bg = "#f7faf8" if i % 2 else "#ffffff"
        price = h["current_price"]
        if isinstance(price, float) and math.isnan(price):
            price_cell, pct_cell = "price unavailable", ""
        else:
            price_cell = f"${price:.2f}"
            pct = h["pct_from_entry"]
            color = "#16a34a" if pct >= 0 else "#dc2626"
            pct_cell = f'<span style="color:{color};font-weight:600;">{pct:+.1f}%</span>'
        if h["signals"]:
            sig = h["signals"][0]
            bgp, fgp = _signal_pill(sig["level"])
            label = f'{sig["emoji"]} {sig["type"].replace("_", " ")}'
        else:
            bgp, fgp = _signal_pill("hold")
            label = "🟢 hold"
        pill = (f'<span style="background:{bgp};color:{fgp};padding:2px 9px;border-radius:999px;'
                f'font-size:11.5px;font-weight:600;">{e(label)}</span>')
        rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px;font-weight:700;">{e(h["ticker"])}</td>'
            f'<td style="padding:8px;">{price_cell}</td>'
            f'<td style="padding:8px;">{pct_cell}</td>'
            f'<td style="padding:8px;">{pill}</td></tr>'
        )
        if h.get("risk_flag"):
            rows.append(
                f'<tr style="background:{bg};"><td colspan="4" '
                f'style="padding:0 8px 8px;font-size:11.5px;color:#b45309;">'
                f'⚠️ {e(h["risk_flag"])}</td></tr>'
            )
    return ('<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            + "".join(rows) + "</table>")


def _candidate_card_html(r, e, green) -> str:
    """Left-bordered card for one ranked candidate."""
    adj = "  ".join(r["adjustments"]) or "no adjustments"
    return (
        f'<div style="border-left:3px solid {green};background:#f7faf8;'
        f'border-radius:0 8px 8px 0;padding:11px 13px;margin-bottom:9px;">'
        f'<div style="font-size:13.5px;"><b>{e(r["ticker"])}</b> &nbsp;'
        f'<span style="color:{green};font-weight:700;">{r["final_score"]:.0f}</span>'
        f'<span style="color:#9ca3af;">/100</span> '
        f'<span style="color:#9ca3af;font-size:11.5px;">(base {r["base_score"]:.0f})</span></div>'
        f'<div style="font-size:12.5px;color:#4b5563;margin-top:4px;">📰 {e(r["news"]["summary"])}</div>'
        f'<div style="font-size:12.5px;color:#4b5563;">🚩 risk {e(r["risk"]["risk_level"])}: '
        f'{e(r["risk"]["reason"])}</div>'
        f'<div style="font-size:11.5px;color:#9ca3af;margin-top:3px;">adj: {e(adj)}</div></div>'
    )


def render_briefing_html(ranked, vetoed, others, excluded, date_str, regime,
                         regime_note, holdings=None) -> str:
    """Styled HTML version of the daily briefing (plain-text fallback stays render_briefing)."""
    e = html.escape
    green = "#0f3d2e"
    P = [
        '<div style="background:#eef0f3;padding:22px;'
        'font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;'
        'border-radius:12px;overflow:hidden;color:#1f2937;">',
        f'<div style="padding:20px 24px;background:{green};color:#ffffff;">'
        f'<div style="font-size:20px;font-weight:700;">Stock Advisor</div>'
        f'<div style="font-size:12.5px;color:#a7d7c5;margin-top:2px;">'
        f'{e(date_str)} &middot; {e(regime)} — {e(regime_note)}</div></div>',
        '<div style="padding:18px 24px 22px;">',
        '<div style="font-size:14px;font-weight:700;color:#0f172a;margin-bottom:10px;">'
        '📊 Your holdings</div>',
        _holdings_html(holdings or [], e),
        '<div style="font-size:14px;font-weight:700;color:#0f172a;margin:20px 0 10px;">'
        'Top candidates</div>',
    ]
    if ranked:
        P.extend(_candidate_card_html(r, e, green) for r in ranked)
    else:
        P.append('<div style="font-size:12.5px;color:#6b7280;">No candidates today.</div>')

    if vetoed:
        P.append('<div style="font-size:14px;font-weight:700;color:#991b1b;margin:20px 0 8px;">'
                 '⛔ Vetoed (do not buy)</div>')
        for v in vetoed:
            P.append(
                '<div style="border-left:3px solid #dc2626;background:#fef2f2;'
                'border-radius:0 8px 8px 0;padding:9px 13px;font-size:12.5px;color:#7f1d1d;'
                f'margin-bottom:6px;"><b>{e(v["ticker"])}</b> — {e(v["veto_reason"])}</div>'
            )

    if others:
        chips = " &middot; ".join(f'{e(o["ticker"])} {o["score"]:.0f}' for o in others)
        P.append('<div style="font-size:12.5px;font-weight:700;color:#374151;margin:18px 0 6px;">'
                 'Other scored</div>')
        P.append(f'<div style="font-size:12.5px;color:#6b7280;">{chips}</div>')

    if excluded:
        items = " &middot; ".join(f'{e(x["ticker"])} — {e(x["reason"])}' for x in excluded)
        P.append('<div style="font-size:12.5px;font-weight:700;color:#374151;margin:14px 0 6px;">'
                 'Excluded (hard filters)</div>')
        P.append(f'<div style="font-size:12.5px;color:#9ca3af;">{items}</div>')

    P.append('<div style="font-size:11.5px;color:#9ca3af;border-top:1px solid #eef0f3;'
             'padding-top:12px;margin-top:18px;">Information only — not financial advice.</div>')
    P.append('</div></div></div>')
    return "".join(P)


def send_email(subject, body, *, host, port, user, password, to_addr,
               html_body=None, smtp_factory=None) -> None:
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
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtp_factory() as server:
        server.login(user, password)
        server.send_message(msg)
