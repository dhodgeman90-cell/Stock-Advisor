# HTML Email Briefing — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)
**Area:** `src/briefing.py`, `src/main.py`, tests

## Problem

The daily briefing is emailed as raw markdown via `msg.set_content(body)`
([src/briefing.py:91](../../src/briefing.py)). Recipients see literal `#`, `**`, and
`-` characters — a wall of plain text. As the tool is shared with others, it needs to
look like a polished product, not a script dump.

## Goal

Send the briefing as a styled HTML email (with a plain-text fallback) that is easy to
scan: a branded header, holdings as a color-coded table, candidates as cards, and
clearly distinguished vetoed names. Reliable rendering across mail clients.

Non-goals (YAGNI): theme configuration/multiple themes, a logo image, Cc/Bcc (a
separately-tracked future item), changing any scoring/exit/briefing *content*.

## Decisions (from brainstorming, visual mockups approved)

1. **Look: "accent header band" (Option B).** Light body for cross-client
   reliability, topped by a deep-green header (`#0f3d2e`) carrying the title and
   date + regime. Light themes render predictably everywhere; dark-mode email is
   inconsistent. The green is a single constant, trivially changeable later.
2. **Render HTML directly from the structured briefing data**, not by converting the
   markdown. No new dependency; full control over tables/pills/colors; pure and
   testable.
3. **Color-coded signal pills** for holdings (🔴 sell = red, 🟡 watch/trim = amber,
   🟢 hold = green) and a **red-accented vetoed block**. Holdings render as a table;
   candidates as left-bordered cards; "other scored" and "excluded" stay compact and
   muted (reference info).
4. **Keep the existing markdown** `render_briefing` as the plain-text version and the
   `reports/` artifact. HTML is additive.

## Approved visual layout

Header band (green) → `📊 Your holdings` table (Ticker / Price / vs entry / Signal
pill) → `Top candidates` cards (score, 📰 news, 🚩 risk, adjustments) → `⛔ Vetoed`
(red block) → `Other scored` (compact line) → `Excluded` (compact muted line) →
disclaimer footer. Empty sections are omitted, matching the markdown briefing.

## Design

### 1. `_signal_pill(level) -> (bg, fg)` helper (new, in `briefing.py`)

Maps a holding signal's `level` to its pill colors, returning a `(background, foreground)`
hex-color tuple:

- `sell` → red (`bg #fee2e2`, `fg #991b1b`)
- `trim` / `watch` → amber (`bg #fef9c3`, `fg #854d0e`)
- `hold` (and unknown/default) → green (`bg #dcfce7`, `fg #166534`)

Single source of truth for signal coloring. Pure; unit-tested directly.

### 2. `render_briefing_html(ranked, vetoed, others, excluded, date_str, regime, regime_note, holdings=None) -> str` (new, in `briefing.py`)

- Same inputs as `render_briefing`.
- Returns a complete HTML document string with **inline CSS** (email clients strip
  `<style>`/external CSS; inline is the reliable choice).
- Builds: green header band; holdings `<table>` with a pill per row (price-unavailable
  rows show "price unavailable"; optional ⚠️ risk-flag line); candidate cards;
  red vetoed block; compact others/excluded lines; footer disclaimer.
- **Every dynamic string escaped** with `html.escape` (news summaries, risk reasons,
  regime note, exclusion reasons come from AI/news/data and may contain `<`/`&`).
- Empty sections omitted exactly as the markdown version omits them.

### 3. `send_email(..., html_body=None)` (modify, in `briefing.py`)

- Add an optional keyword-only `html_body` parameter.
- Plain text stays the primary content: `msg.set_content(body)`.
- When `html_body` is provided: `msg.add_alternative(html_body, subtype="html")`,
  producing a standard `multipart/alternative` message (HTML preferred, plain-text
  fallback).
- Backward compatible: omitting `html_body` yields the current single-part plain-text
  email; existing callers and tests are unaffected. `smtp_factory` injection (already
  present) is used to assert structure in tests.

### 4. `main.py` wiring (modify)

In the existing email block (the full-briefing path with an API key — the no-key path
returns before emailing and is unchanged), build
`html = briefing.render_briefing_html(ranked, vetoed, others, excluded, date_str, context["regime"], context["note"], holdings=holdings)`
from data already in scope, and pass `html_body=html` to `send_email`. One added call;
no restructuring.

## Testing (TDD, matching the existing pytest suite)

- `_signal_pill`: `sell`→red, `trim`/`watch`→amber, `hold`→green, unknown→green default.
- `render_briefing_html`:
  - contains the header band text (title + date), a `<table` for holdings, a pill with
    the correct color for each signal level, candidate cards, and a vetoed block;
  - omits empty sections (no holdings → the styled "no tracked positions" note; no
    vetoed → no vetoed block);
  - a news summary containing `<b>&` is escaped (no raw `<b>` in output);
  - a NaN holding price renders "price unavailable", not a number.
- `send_email`: with `html_body`, the captured message `is_multipart()` and has both a
  `text/plain` and a `text/html` part; without `html_body`, it is single-part
  `text/plain`. (Uses the injectable `smtp_factory`.)

## Edge cases

- No holdings / no candidates / no vetoed: sections omitted or show the same neutral
  notes as the markdown briefing.
- Price unavailable (NaN): "price unavailable" cell.
- Untrusted dynamic text: escaped via `html.escape`.

## Out of scope

Multiple/!configurable themes, logo image, Cc/Bcc support, any change to briefing
content or scoring. The accent color is a single constant that can be changed later.
