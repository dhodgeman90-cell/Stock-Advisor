# Objective Presets ("Risk Slider") — Design

**Date:** 2026-06-17
**Status:** Approved design, not yet planned/implemented
**Type:** Additive feature, shippable as a later update

## Summary

Let each user pick an **objective preset** — a labeled notch on a slider running from
*Conservative* to *Aggressive Swing* — that adjusts both **which trades the engine
surfaces** and **how the briefing reads**. More aggressive presets also unlock
**multiple / on-demand briefings per day** and make the **in-app briefing the primary
surface**, with email as an opt-in copy.

This is intentionally additive: it defaults every existing user to `balanced`, which
reproduces today's exact behavior, so the feature ships without disturbing anyone.

## Why this is small (not a rewrite)

Engine behavior is already config-driven, and there is already a per-user profile system:

- `config/weights.yaml` — signal weights (breakout / volume / momentum / trend / pullback)
- `config/exits.yaml` — stop-loss %, trailing-stop %, take-profit mode, max hold days, backtest buy threshold
- `config/signals.yaml` — social/congress/discovery thresholds
- `src/profile.py` — per-user `config/` seeded from `defaults/`, rooted at `%APPDATA%/StockAdvisor`
- `src/routes_briefing.py` — already has on-demand run (`POST /api/run`) and in-app HTML view (`GET /api/briefing/today`)

A preset is therefore just **a named bundle of values for files that already exist**, plus
a delivery default and a tone. On-demand and in-app viewing already work; the only
structural gap is report storage (see Multiple Briefings below).

## Honest scope boundary

The engine is a **daily swing tool**: one run per day on daily bars. A literal "aggressive
day trader" (intraday entries/exits on intraday data) is **out of scope** — it would require
an intraday data feed and intraday run cadence, a separate and much larger project. The most
aggressive preset is therefore named **"Aggressive Swing,"** not "Day Trader." Labeling stays
honest about what the engine can actually do.

## The presets

| | Conservative | Balanced (today) | Active | Aggressive Swing |
|---|---|---|---|---|
| Weights (brk/vol/mom/trend/pull) | 15/20/10/40/15 | 30/30/20/15/5 | 32/30/23/12/3 | 35/30/25/10/0 |
| Stop / trailing | 8% / 12% | 5% / 6% | 5% / 5% | 4% / 4% |
| Max hold | 250d | 250d | ~90d | ~30d |
| Buy threshold | 75 | 65 | 60 | 55 |
| Delivery default | Email, 1×/day | Email + in-app, 1×/day | In-app + email, on-demand | In-app primary, multiple/on-demand |
| Tone | Calm, trend/fundamentals | Neutral | Slightly punchy | Punchy, momentum framing |

`Balanced` MUST equal the current shipped defaults exactly — it is the migration target.

Values above are the starting point; each preset must be backtested (see Validation) and
may be tuned before release.

## UI

A slider control in the existing settings screen that **snaps to the 4 named notches**
(no continuous 0–100). Rationale: only named bundles can be backtested and explained to a
user; in-between positions would be fake precision. This is how risk profiles ship in the
industry (Betterment/Wealthfront-style named profiles). The control may *look* continuous
but commits to one of four discrete values.

## Components

1. **Preset definitions** — one new module/data file mapping each preset name to its
   weights/exits/signals overrides, delivery default, and tone key. Single source of truth.
2. **`objective` profile field** — stored per-user; default `balanced`. When loading config,
   the active preset's values override `weights.yaml` / `exits.yaml` / `signals.yaml`.
   (Decision for the plan: apply as an in-memory override at load time vs. writing values
   into the user's YAML. Lean toward in-memory override so presets stay swappable and the
   user's files aren't mutated.)
3. **Settings route + UI** — read/write `objective` via the existing settings plumbing.
4. **Delivery default** — objective sets whether email and/or in-app is emphasized; email
   becomes an opt-in "also send me a copy." In-app is primary overall (per approved
   delivery model).
5. **Tone** — pass the active preset's tone key into the briefing/LLM template so copy shifts
   register (calm → punchy). The only piece touching the briefing/AI layer rather than pure
   config.
6. **Multiple briefings per day** — see below.

## Multiple briefings per day (the one structural change)

Today reports are keyed by date: `reports/{date}.html`. A second run the same day
**overwrites** the first. To support several briefings a day:

- Timestamp report filenames (e.g. `reports/{date}-{HHMM}.html`) so runs don't clobber.
- Add a **history list** endpoint + a simple in-app list so the user can scroll back through
  the day's briefings.
- `GET /api/briefing/today` keeps returning the latest; the list surfaces the rest.

Keep filenames lexically sortable so chronological order is free (the current
`sorted(glob)` approach in `routes_briefing.py` still works).

## Delivery model (approved)

**In-app primary, email optional.** The app is the main place to read briefings (dashboard
+ history). Email stays as an opt-in copy. The objective preset sets the *default* emphasis:
conservative leans on email, aggressive lives in-app with multiple/on-demand runs. Email is
not removed — it is what the conservative/passive user wants.

## Migration / shipping as an update

- Add `objective` with default `balanced`.
- `balanced` preset values == current defaults → existing users see zero behavior change
  until they move the slider.
- New report filename format is additive; old `{date}.html` files still load via the
  existing glob.
- No data migration required.

## Validation

- **Backtest each preset** with the existing backtest harness (`src/backtest.py`,
  `config/exits.yaml` backtest block) and confirm they produce materially different
  behavior (turnover, hold length, drawdown). A preset that doesn't differ from its
  neighbor should be retuned or dropped.
- Tests: preset → config-override mapping; `objective` round-trips through profile
  save/load; timestamped report storage doesn't clobber and history lists in order;
  default `objective` reproduces current behavior.

## Backtest validation (2026-06-17)

Driving the harness's pure `simulate_ticker` with each preset's applied weights/exits
over four deterministic synthetic regimes (strong uptrend, choppy-up, sideways,
downtrend) confirms the slider produces **materially different, monotonic** behavior:

| Preset | Trades | Avg hold (d) | Win rate | Threshold | Trail % |
|---|---|---|---|---|---|
| Conservative | 17 | 38 | 53% | 75 | 12 |
| Balanced | 71 | 9 | 34% | 65 | 6 |
| Active | 96 | 7 | 30% | 60 | 5 |
| Aggressive | 131 | 5 | 30% | 55 | 4 |

Trade count rises and average hold falls smoothly from Conservative → Aggressive,
which is exactly the intended distinction. **These are synthetic, illustrative numbers
that validate the mechanism — not return forecasts.** A real-data backtest (and paper
trading) remains the pre-distribution step before trusting magnitudes, consistent with
the app's own overfitting caveat.

## Out of scope (future ideas, not this spec)

- Intraday / true day trading (separate data feed + cadence).
- Push notifications / alerts when a new on-demand briefing is ready.
- Per-objective watchlists.
- A custom "advanced" preset exposing raw knobs (was considered, deferred).
