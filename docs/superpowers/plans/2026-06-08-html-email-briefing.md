# HTML Email Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Email the daily briefing as a styled HTML message (green-banded layout, color-coded holdings table, candidate cards) with a plain-text fallback.

**Architecture:** Add `render_briefing_html` (+ small private helpers) to `src/briefing.py` that builds the approved layout directly from the structured briefing data with inline CSS. Extend `send_email` to send `multipart/alternative` (existing markdown as plain text + new HTML). Wire it into `main.py`'s email block. No new dependencies; the markdown `render_briefing` and `reports/` output are unchanged.

**Tech Stack:** Python 3.14 stdlib (`email.message`, `html.escape`, `math`), pytest. Run from repo root `C:\VS Code\Stock Advisor` with `& .\.venv\Scripts\python.exe -m pytest`.

---

## File Structure

- **Modify:** `src/briefing.py` — add `import html`; add `_PILL_COLORS`, `_signal_pill`, `_holdings_html`, `_candidate_card_html`, `render_briefing_html`; extend `send_email` with an optional `html_body`.
- **Modify:** `src/main.py` — in the email block, build the HTML and pass `html_body=`.
- **Modify (tests):** `tests/test_briefing.py` — tests for the pill helper, the HTML renderer, and multipart sending. Reuses `_adjudicated`/`_holding` helpers and `tests.fakes.FakeSMTP` already in the file.

Holding signal shape (already used elsewhere): `{"type", "level", "emoji", "detail"}`,
where `level` is one of `sell` / `trim` / `watch` / `hold`. Pill color is driven by `level`.

---

### Task 1: `_signal_pill` color helper

**Files:**
- Modify: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_briefing.py`:

```python
def test_signal_pill_colors_by_level():
    assert briefing._signal_pill("sell")  == ("#fee2e2", "#991b1b")   # red
    assert briefing._signal_pill("trim")  == ("#fef9c3", "#854d0e")   # amber
    assert briefing._signal_pill("watch") == ("#fef9c3", "#854d0e")   # amber
    assert briefing._signal_pill("hold")  == ("#dcfce7", "#166534")   # green


def test_signal_pill_unknown_level_defaults_to_green():
    assert briefing._signal_pill("whatever") == ("#dcfce7", "#166534")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -k signal_pill -v`
Expected: FAIL with `AttributeError: module 'src.briefing' has no attribute '_signal_pill'`

- [ ] **Step 3: Write minimal implementation**

In `src/briefing.py`, change the import block at the top from:

```python
import math
from email.message import EmailMessage
```

to:

```python
import html
import math
from email.message import EmailMessage
```

Then add near the top of the file (after the imports, before `render_holdings_section`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -k signal_pill -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add src/briefing.py tests/test_briefing.py
git commit -m "feat(briefing): signal pill color helper for HTML email"
```

---

### Task 2: `render_briefing_html` and its section helpers

**Files:**
- Modify: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_briefing.py`:

```python
def test_render_briefing_html_has_header_table_and_pills():
    ranked = [_adjudicated("MSFT", 78, 74, "cloud demand strong", "low", "no flags", ["+4 news"])]
    holdings = [
        _holding("NVDA", 128.40, 6.6, []),                              # clean -> green hold
        _holding("AAPL", 182.10, -3.2,
                 [{"type": "momentum_fade", "level": "watch", "emoji": "🟡",
                   "detail": "rsi cooling"}]),
    ]
    html_out = briefing.render_briefing_html(
        ranked, [], [], [], "2026-06-08", "risk_on", "Broad uptrend.", holdings=holdings)
    assert "Stock Advisor" in html_out
    assert "2026-06-08" in html_out
    assert "<table" in html_out                       # holdings table
    assert "#dcfce7" in html_out                       # green hold pill (NVDA, no signals)
    assert "#fef9c3" in html_out                       # amber watch pill (AAPL)
    assert "MSFT" in html_out                          # candidate card


def test_render_briefing_html_escapes_untrusted_text():
    ranked = [_adjudicated("X", 70, 70, "deal <b>&</b> close", "low", "fine", [])]
    html_out = briefing.render_briefing_html(
        ranked, [], [], [], "2026-06-08", "risk_on", "ok", holdings=[])
    assert "deal <b>&</b>" not in html_out             # raw HTML must not pass through
    assert "&lt;b&gt;" in html_out                      # it is escaped instead


def test_render_briefing_html_handles_unavailable_price():
    holdings = [_holding("NVDA", float("nan"), 0.0, [])]
    html_out = briefing.render_briefing_html(
        [], [], [], [], "2026-06-08", "risk_on", "ok", holdings=holdings)
    assert "price unavailable" in html_out
    assert "nan" not in html_out.lower()


def test_render_briefing_html_omits_empty_sections_and_shows_vetoed():
    vetoed = [{"ticker": "GME", "veto_reason": "headline spike"}]
    html_out = briefing.render_briefing_html(
        [], vetoed, [], [], "2026-06-08", "risk_on", "ok", holdings=[])
    assert "Vetoed" in html_out
    assert "headline spike" in html_out
    assert "Other scored" not in html_out              # empty others omitted
    assert "Excluded" not in html_out                  # empty excluded omitted
    assert "No tracked positions" in html_out          # empty holdings note
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -k render_briefing_html -v`
Expected: FAIL with `AttributeError: module 'src.briefing' has no attribute 'render_briefing_html'`

- [ ] **Step 3: Write minimal implementation**

In `src/briefing.py`, add these three functions after `render_briefing` (and before `send_email`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -k render_briefing_html -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add src/briefing.py tests/test_briefing.py
git commit -m "feat(briefing): render_briefing_html styled email layout"
```

---

### Task 3: `send_email` multipart support

**Files:**
- Modify: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_briefing.py`:

```python
def test_send_email_sends_multipart_when_html_given():
    fake = FakeSMTP()
    briefing.send_email(
        "Subj", "plain body", host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        html_body="<p>hi</p>", smtp_factory=lambda: fake,
    )
    msg = fake.sent_message
    assert msg.is_multipart()
    types = [p.get_content_type() for p in msg.iter_parts()]
    assert "text/plain" in types
    assert "text/html" in types


def test_send_email_plain_only_when_no_html():
    fake = FakeSMTP()
    briefing.send_email(
        "Subj", "plain body", host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        smtp_factory=lambda: fake,
    )
    assert not fake.sent_message.is_multipart()
    assert fake.sent_message.get_content_type() == "text/plain"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -k "send_email_sends_multipart or send_email_plain_only" -v`
Expected: FAIL — `send_email() got an unexpected keyword argument 'html_body'`

- [ ] **Step 3: Write minimal implementation**

In `src/briefing.py`, change the `send_email` signature from:

```python
def send_email(subject, body, *, host, port, user, password, to_addr, smtp_factory=None) -> None:
```

to:

```python
def send_email(subject, body, *, host, port, user, password, to_addr,
               html_body=None, smtp_factory=None) -> None:
```

Then, inside `send_email`, immediately after the line `msg.set_content(body)`, add:

```python
    if html_body:
        msg.add_alternative(html_body, subtype="html")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -v`
Expected: PASS — the two new send tests pass and the existing `test_send_email_logs_in_and_sends` still passes (html_body defaults to None).

- [ ] **Step 5: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add src/briefing.py tests/test_briefing.py
git commit -m "feat(briefing): send_email supports multipart HTML alternative"
```

---

### Task 4: Wire HTML into `main.py` and verify end-to-end

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Build and pass the HTML in the email block**

In `src/main.py`, find the email block:

```python
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
```

and replace it with:

```python
    # Optional email
    if all(os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            html_body = briefing.render_briefing_html(
                ranked, vetoed, others, excluded, date_str,
                context["regime"], context["note"], holdings=holdings,
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
```

(Note: `ranked`, `vetoed`, `others`, `excluded`, `holdings`, `context`, and `text` are all
already defined earlier in `run()`, just above this block.)

- [ ] **Step 2: Run the full test suite (no regression)**

Run: `& .\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS — all prior tests plus the 8 new ones (was 90; expect ~98).

- [ ] **Step 3: Real end-to-end send (user has email configured)**

Run: `& .\.venv\Scripts\python.exe -m src.main`
Expected: prints `[briefing emailed]`; the user confirms the email now arrives **styled**
(green header band, holdings table with colored pills) rather than plain markdown. This is
a real, paid AI run — expected.

- [ ] **Step 4: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add src/main.py
git commit -m "feat(main): email the styled HTML briefing alongside plain text"
```

---

## Notes for the implementer

- **Escaping:** `e = html.escape` wraps every dynamic string (tickers, news summaries,
  risk reasons, regime note, exclusion/veto reasons). Static layout strings and emoji are
  not escaped (emoji are unaffected by escaping anyway). This prevents AI/news text from
  breaking the HTML.
- **Inline CSS only:** email clients strip `<style>` blocks and external CSS, so all styling
  is inline on each element. Don't refactor it into a stylesheet.
- **Plain text is the fallback, not removed:** `text` (the markdown from `render_briefing`)
  is still the primary `set_content` body and still saved to `reports/`. The HTML is an
  added alternative.
- **Only the AI path emails:** the no-API-key branch returns before the email block, so HTML
  is only built where `ranked`/`vetoed`/`context` exist. No change needed there.
- **Accent color** is the single constant `green = "#0f3d2e"` in `render_briefing_html` —
  change it there if the brand color ever changes.
```
