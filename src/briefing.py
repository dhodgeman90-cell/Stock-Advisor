import html
import math
from email.message import EmailMessage

from src import verdict


def _clip(text, n=160) -> str:
    """Defensive truncation so a run-on LLM sentence can't blow up a card. The prompts ask
    for <=12 words, but the model overruns; this is the belt to that suspenders."""
    text = str(text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


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


def _is_stale(as_of, run_date) -> bool:
    """True when the priced bar predates the run date (ISO strings sort chronologically),
    so a valid-but-stale price can be labelled instead of passing as today's."""
    return bool(as_of and run_date and str(as_of) < str(run_date))


def render_holdings_section(holdings, run_date=None) -> str:
    """Markdown block for current holdings + their exit signals. Leads the briefing."""
    lines = ["## 📊 Your holdings"]
    if not holdings:
        lines.append("_No tracked positions._")
        return "\n".join(lines)
    for h in holdings:
        price = h["current_price"]
        if isinstance(price, float) and math.isnan(price):
            lines.append(f"- **{h['ticker']}**: price unavailable")
        else:
            stale = f" — _as of {h['as_of']}_" if _is_stale(h.get("as_of"), run_date) else ""
            lines.append(
                f"- **{h['ticker']}**: ${price:.2f} "
                f"({h['pct_from_entry']:+.1f}% from entry){stale}"
            )
        if h["signals"]:
            for s in h["signals"]:
                lines.append(f"    - {s['emoji']} {s['type'].replace('_', ' ')}: {s['detail']}")
        else:
            lines.append("    - 🟢 holding — no exit signal")
        if h.get("risk_flag"):
            lines.append(f"    - ⚠️ {h['risk_flag']}")
    return "\n".join(lines)


def _amount_range(low, high) -> str:
    """Compact dollar range, e.g. '$100k–$250k' or '$50k'."""
    def fmt(v):
        return f"${v / 1000:.0f}k" if v >= 1000 else f"${v:.0f}"
    return fmt(low) if low == high else f"{fmt(low)}–{fmt(high)}"


def _candidate_insight_lines(r) -> list:
    """Plain insight strings (no markdown prefix) for the new signal sources.

    Returns only the badges that actually have data, so a candidate with no congress /
    insider / analyst / earnings / social signal stays uncluttered.
    """
    lines = []
    c = r.get("congress")
    if c and c.get("net_side"):
        disc = c.get("most_recent_disclosure")
        when = f", disclosed {disc}" if disc else ""
        lines.append(f"🏛️ Congress {c['net_side']} ({c.get('n_members', 1)} member(s){when}) "
                     f"— note: up to 45-day disclosure lag")
    ins = r.get("insider")
    if ins and ins.get("net_side"):
        verb = "buying" if ins["net_side"] == "buy" else "selling"
        lines.append(f"👔 Insider {verb} ({ins.get('n_buys', 0)} buys / {ins.get('n_sells', 0)} sells)")
    a = r.get("analyst")
    if a and a.get("rating"):
        up = a.get("upside_pct")
        up_txt = f", target {up:+.0f}%" if up is not None else ""
        lines.append(f"🎯 Analysts {a['rating'].replace('_', ' ')}{up_txt}")
    earn = r.get("earnings")
    if earn and earn.get("days_until") is not None:
        lines.append(f"📅 Earnings in {earn['days_until']}d — gap risk for a swing trade")
    sec = r.get("edgar")
    if sec:
        if sec.get("severe"):
            lines.append(f"📄 SEC 8-K: {sec.get('severe_reason') or 'severe filing'} — elevated risk")
        elif sec.get("catalyst_types"):
            lines.append(f"📄 SEC 8-K: {', '.join(sec['catalyst_types'])}")
        elif sec.get("negative"):
            lines.append("📄 SEC 8-K: adverse filing")
        if sec.get("activist"):
            lines.append("📄 Activist 13D stake filed")
    opt = r.get("options")
    if opt and opt.get("direction") in ("bullish", "bearish") and opt.get("pc_ratio") is not None:
        flow = "call-heavy" if opt["direction"] == "bullish" else "put-heavy"
        lines.append(f"⚙️ Options flow {flow} (P/C {opt['pc_ratio']:.2f})")
    sh = r.get("short")
    if sh and sh.get("pct_float") is not None and sh["pct_float"] >= 20:
        dtc = sh.get("days_to_cover")
        dtc_txt = f", {dtc:.1f}d to cover" if dtc is not None else ""
        lines.append(f"🩳 Short interest {sh['pct_float']:.0f}% of float{dtc_txt}")
    rev = r.get("revision")
    if rev and rev.get("revision_trend") in ("up", "down"):
        arrow = "↑ rising" if rev["revision_trend"] == "up" else "↓ falling"
        lines.append(f"📈 Analyst estimates {arrow} ({rev.get('n_up', 0)}↑/{rev.get('n_down', 0)}↓)")
    soc = r.get("social")
    if soc:
        lines.append(f"💬 {soc}")
    return lines


def render_rotation_section(plan) -> str:
    """Markdown 'Today's rotation' block — the daily transition recommendation."""
    plan = plan or {}
    exits, trims = plan.get("exits", []), plan.get("trims", [])
    adds, hold = plan.get("adds", []), plan.get("hold", [])
    L = ["## 🔄 Today's rotation"]
    if not (exits or trims or adds):
        L.append("_No rotation today — hold steady._")
        return "\n".join(L)
    for x in exits:
        L.append(f"- 🔴 **Exit {x['ticker']}** — {x['reason']}")
    for t in trims:
        L.append(f"- 🟡 **Trim {t['ticker']}** — {t['reason']}")
    for a in adds:
        tag = " (high conviction)" if a.get("conviction") == "high" else ""
        L.append(f"- 🟢 **Add {a['ticker']}** ({a['final_score']:.0f}/100){tag} — {a['reason']}")
    if hold:
        L.append(f"- ⚪ Hold: {', '.join(h['ticker'] for h in hold)}")
    return "\n".join(L)


def render_discovery_section(congress_movers, wsb_movers) -> str:
    """Markdown 'Outside the watchlist' block — actionable signals on untracked names.

    Returns '' when there is nothing to surface, so the caller can omit it cleanly.
    """
    congress_movers = congress_movers or []
    wsb_movers = wsb_movers or []
    if not (congress_movers or wsb_movers):
        return ""
    L = ["## 🔭 Outside the watchlist",
         "_Signals on names you don't hold or track. Congress filings carry up to a 45-day lag._"]
    if congress_movers:
        L.append("**Big congressional trades:**")
        for t in congress_movers:
            verb = "🟢 buy" if t["side"] == "buy" else "🔴 sell"
            amt = _amount_range(t["amount_low"], t["amount_high"])
            L.append(f"- **{t['ticker']}**: {verb} {amt} — {t['member']} "
                     f"(disclosed {t['disclosure_date']})")
    if wsb_movers:
        L.append("**WSB surging:**")
        for w in wsb_movers:
            chg = w.get("mentions_change")
            chg_txt = f" (+{chg} mentions)" if chg is not None else ""
            L.append(f"- **{w['ticker']}**: {w['mentions']} mentions{chg_txt}")
    return "\n".join(L)


def _pct(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def _rate(v):
    return "n/a" if v is None else f"{v:.0f}%"


def render_reality_check(summary) -> str:
    """Markdown 'Reality check' block: how the app's OWN past picks are doing vs SPY, shown
    at the decision moment so the reader can't act on today's list without seeing the record.
    '' when nothing is logged yet; a plain 'too few to judge' note below the sample floor."""
    if not summary:
        return ""
    L = ["## 🧭 Reality check"]
    if not summary.get("enough"):
        L.append(f"_{summary.get('n_matured', 0)} matured picks logged — too few to judge yet "
                 "(building toward 30+). Numbers withheld until the sample is meaningful._")
        return "\n".join(L)
    verdict = "underperforming SPY" if summary["underperforming"] else "beating SPY"
    L.append(f"This system's own picks are currently **{verdict}**. Read this before acting "
             "on today's list.")
    L.append(f"- +5d vs SPY (actionable cohort): {_pct(summary['cohort_alpha_5d'])} alpha · "
             f"beat-SPY {_rate(summary['beat_spy_rate'])} · {summary['n_matured']} matured picks")
    L.append(f"- Exit-rule sim: expectancy {_pct(summary['sim_expectancy'])} · "
             f"win {_rate(summary['sim_win'])}")
    return "\n".join(L)


def _reality_check_html(summary, e) -> str:
    """Styled reality-check banner for the HTML email; '' when nothing is logged."""
    if not summary:
        return ""
    if not summary.get("enough"):
        return ('<div style="background:#f3f4f6;border-radius:8px;padding:11px 13px;'
                'margin-bottom:14px;font-size:12.5px;color:#4b5563;">'
                f'🧭 <b>Reality check:</b> {summary.get("n_matured", 0)} matured picks — too few '
                'to judge yet (building toward 30+).</div>')
    under = summary["underperforming"]
    bg, fg = ("#fef2f2", "#7f1d1d") if under else ("#ecfdf5", "#065f46")
    verdict = "underperforming SPY" if under else "beating SPY"
    return (f'<div style="background:{bg};border-radius:8px;padding:11px 13px;margin-bottom:14px;'
            f'font-size:12.5px;color:{fg};">'
            f'🧭 <b>Reality check:</b> this system\'s own picks are currently <b>{verdict}</b>. '
            f'+5d cohort alpha {_pct(summary["cohort_alpha_5d"])} · '
            f'beat-SPY {_rate(summary["beat_spy_rate"])} · '
            f'exit-sim expectancy {_pct(summary["sim_expectancy"])} · win {_rate(summary["sim_win"])} · '
            f'{summary["n_matured"]} matured picks.</div>')


def _thin_data_note(r) -> str:
    """' · thin data (k/7)' when fewer than 3 of the 7 enrichment signals resolved for this
    pick, so a momentum-only score isn't mistaken for a corroborated one. Empty when the count
    is unknown (report-backfilled picks predate the field) or healthy. Shared by both renderers
    so the markdown and HTML briefings stay in sync."""
    live = r.get("data_signals_live")
    return f" · thin data ({live}/7)" if live is not None and live < 3 else ""


def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note,
                    holdings=None, rotation_plan=None, discovery=None, tone_line=None,
                    scorecard_summary=None, buy_threshold=65) -> str:
    """Render the enriched daily briefing (Phase 2 + Phase 3 holdings + signal upgrade).

    `ranked` is pre-sorted by final_score. The rotation plan and holdings lead the
    briefing; the discovery feed (untracked signals) trails it. `tone_line` is an
    optional one-line strategy framing (set by the active objective preset). Each candidate
    leads with a single Buy/Watch/Avoid verdict; the raw signal detail is demoted below it.
    """
    underperforming = bool(scorecard_summary and scorecard_summary.get("enough")
                           and scorecard_summary.get("underperforming"))
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
    ]
    if tone_line:
        L.append(f"_{tone_line}_")
    rc = render_reality_check(scorecard_summary)
    if rc:
        L += ["", rc]
    L += [
        "",
        render_rotation_section(rotation_plan),
        "",
        render_holdings_section(holdings, run_date=date_str),
        "",
        "## Top candidates",
    ]
    if not ranked:
        L.append("_No candidates today._")
    for r in ranked:
        v = verdict.classify(r, buy_threshold, underperforming=underperforming)
        L.append(f"- **{r['ticker']}** — {v['call']}: {v['reason']} "
                 f"_(score {r['final_score']:.0f}/100 · {v['confidence']} confidence"
                 f"{_thin_data_note(r)})_")
        # Supporting detail, demoted below the verdict (was a raw 'adj:' math dump).
        L.append(f"    - 📰 {_clip(r['news']['summary'])}")
        L.append(f"    - 🚩 risk {r['risk']['risk_level']}: {_clip(r['risk']['reason'])}")
        for line in _candidate_insight_lines(r):
            L.append(f"    - {line}")

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

    if discovery:
        disc_text = render_discovery_section(discovery.get("congress"), discovery.get("wsb"))
        if disc_text:
            L.append("")
            L.append(disc_text)

    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"


def _holdings_html(holdings, e, run_date=None) -> str:
    """HTML table of holdings with a color-coded signal pill per row."""
    if not holdings:
        return ('<div style="font-size:12.5px;color:#6b7280;">'
                'No tracked positions.</div>')
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
            stale = (f'<div style="font-size:10.5px;color:#9ca3af;">as of {e(str(h["as_of"]))}</div>'
                     if _is_stale(h.get("as_of"), run_date) else "")
            price_cell = f"${price:.2f}{stale}"
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


# (background, foreground) for the Buy/Watch/Avoid verdict pill.
_VERDICT_COLORS = {
    "Buy":   ("#dcfce7", "#166534"),   # green
    "Watch": ("#fef9c3", "#854d0e"),   # amber
    "Avoid": ("#fee2e2", "#991b1b"),   # red
}


def _candidate_card_html(r, e, green, buy_threshold=65, underperforming=False) -> str:
    """Left-bordered card: one clear verdict up top, the raw signal detail collapsed below."""
    v = verdict.classify(r, buy_threshold, underperforming=underperforming)
    bg, fg = _VERDICT_COLORS.get(v["call"], _VERDICT_COLORS["Watch"])
    insight_html = "".join(
        f'<div style="font-size:12px;color:#4b5563;margin-top:2px;">{e(line)}</div>'
        for line in _candidate_insight_lines(r)
    )
    details = (
        '<details style="margin-top:6px;">'
        '<summary style="font-size:11px;color:#9ca3af;cursor:pointer;">details</summary>'
        f'<div style="font-size:12.5px;color:#4b5563;margin-top:4px;">📰 {e(_clip(r["news"]["summary"]))}</div>'
        f'<div style="font-size:12.5px;color:#4b5563;">🚩 risk {e(r["risk"]["risk_level"])}: '
        f'{e(_clip(r["risk"]["reason"]))}</div>'
        f'{insight_html}</details>'
    )
    return (
        f'<div style="border-left:3px solid {green};background:#f7faf8;'
        f'border-radius:0 8px 8px 0;padding:11px 13px;margin-bottom:9px;">'
        f'<div style="font-size:13.5px;"><b>{e(r["ticker"])}</b> &nbsp;'
        f'<span style="background:{bg};color:{fg};padding:1px 9px;border-radius:999px;'
        f'font-size:11.5px;font-weight:700;">{e(v["call"])}</span> '
        f'<span style="color:#4b5563;font-size:12.5px;">{e(v["reason"])}</span></div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:3px;">'
        f'score {r["final_score"]:.0f}/100 · {e(v["confidence"])} confidence{_thin_data_note(r)}</div>'
        f'{details}</div>'
    )


def _rotation_html(plan, e, green) -> str:
    """Styled 'Today's rotation' block for the HTML email."""
    plan = plan or {}
    exits, trims = plan.get("exits", []), plan.get("trims", [])
    adds, hold = plan.get("adds", []), plan.get("hold", [])
    rows = []
    if not (exits or trims or adds):
        rows.append('<div style="font-size:12.5px;color:#6b7280;">No rotation today — hold steady.</div>')
    else:
        for x in exits:
            rows.append(f'<div style="font-size:12.5px;color:#7f1d1d;">🔴 <b>Exit {e(x["ticker"])}</b> — {e(x["reason"])}</div>')
        for t in trims:
            rows.append(f'<div style="font-size:12.5px;color:#854d0e;">🟡 <b>Trim {e(t["ticker"])}</b> — {e(t["reason"])}</div>')
        for a in adds:
            tag = " (high conviction)" if a.get("conviction") == "high" else ""
            rows.append(f'<div style="font-size:12.5px;color:#166534;">🟢 <b>Add {e(a["ticker"])}</b> '
                        f'({a["final_score"]:.0f}/100){tag} — {e(a["reason"])}</div>')
        if hold:
            rows.append(f'<div style="font-size:12px;color:#6b7280;">⚪ Hold: '
                        f'{e(", ".join(h["ticker"] for h in hold))}</div>')
    return ('<div style="font-size:14px;font-weight:700;color:#0f172a;margin-bottom:8px;">'
            '🔄 Today\'s rotation</div>'
            f'<div style="background:#f7faf8;border-radius:8px;padding:11px 13px;'
            f'border-left:3px solid {green};margin-bottom:6px;">' + "".join(rows) + '</div>')


def _discovery_html(congress_movers, wsb_movers, e) -> str:
    """Styled 'Outside the watchlist' block; '' when there is nothing to show."""
    congress_movers = congress_movers or []
    wsb_movers = wsb_movers or []
    if not (congress_movers or wsb_movers):
        return ""
    rows = ['<div style="font-size:14px;font-weight:700;color:#0f172a;margin:20px 0 4px;">'
            '🔭 Outside the watchlist</div>',
            '<div style="font-size:11.5px;color:#9ca3af;margin-bottom:8px;">'
            'Names you don\'t hold or track. Congress filings carry up to a 45-day lag.</div>']
    for t in congress_movers:
        verb = "🟢 buy" if t["side"] == "buy" else "🔴 sell"
        amt = _amount_range(t["amount_low"], t["amount_high"])
        rows.append(f'<div style="font-size:12.5px;color:#4b5563;"><b>{e(t["ticker"])}</b>: '
                    f'{verb} {amt} — {e(t["member"])} (disclosed {e(str(t["disclosure_date"]))})</div>')
    for w in wsb_movers:
        chg = w.get("mentions_change")
        chg_txt = f" (+{chg} mentions)" if chg is not None else ""
        rows.append(f'<div style="font-size:12.5px;color:#4b5563;"><b>{e(w["ticker"])}</b>: '
                    f'{w["mentions"]} mentions{e(chg_txt)}</div>')
    return "".join(rows)


def render_briefing_html(ranked, vetoed, others, excluded, date_str, regime,
                         regime_note, holdings=None, rotation_plan=None, discovery=None,
                         tone_line=None, scorecard_summary=None, buy_threshold=65) -> str:
    """Styled HTML version of the daily briefing (plain-text fallback stays render_briefing)."""
    e = html.escape
    green = "#0f3d2e"
    underperforming = bool(scorecard_summary and scorecard_summary.get("enough")
                           and scorecard_summary.get("underperforming"))
    tone_html = (f'<div style="font-size:11.5px;color:#cdeede;margin-top:4px;'
                 f'font-style:italic;">{e(tone_line)}</div>') if tone_line else ""
    P = [
        '<div style="background:#eef0f3;padding:22px;'
        'font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;'
        'border-radius:12px;overflow:hidden;color:#1f2937;">',
        f'<div style="padding:20px 24px;background:{green};color:#ffffff;">'
        f'<div style="font-size:20px;font-weight:700;">Stock Advisor</div>'
        f'<div style="font-size:12.5px;color:#a7d7c5;margin-top:2px;">'
        f'{e(date_str)} &middot; {e(regime)} — {e(regime_note)}</div>{tone_html}</div>',
        '<div style="padding:18px 24px 22px;">',
        _reality_check_html(scorecard_summary, e),
        _rotation_html(rotation_plan, e, green),
        '<div style="font-size:14px;font-weight:700;color:#0f172a;margin:18px 0 10px;">'
        '📊 Your holdings</div>',
        _holdings_html(holdings or [], e, date_str),
        '<div style="font-size:14px;font-weight:700;color:#0f172a;margin:20px 0 10px;">'
        'Top candidates</div>',
    ]
    if ranked:
        P.extend(_candidate_card_html(r, e, green, buy_threshold, underperforming)
                 for r in ranked)
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

    if discovery:
        disc_html = _discovery_html(discovery.get("congress"), discovery.get("wsb"), e)
        if disc_html:
            P.append(disc_html)

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
