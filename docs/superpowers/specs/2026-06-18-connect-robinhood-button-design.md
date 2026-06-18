# Design: "Connect Robinhood" button (BYO keys, SaaS-ready)

**Date:** 2026-06-18
**Status:** Approved (design); implementation plan pending
**Author:** Dane + Claude

## Problem

The standalone app can sync live Robinhood holdings (via SnapTrade, read-only) but has
**no UI to set it up**. Linking today requires the CLI (`python -m src.link_broker`) and
hand-editing a `.env` file in the per-user profile (`%APPDATA%\StockAdvisor\.env`). That is
fine for the owner but a non-starter for a new user. We want a "Connect Robinhood" button in
the Integrations tab that is as easy and intuitive as possible — while staying secure.

## Key decision: where do the SnapTrade keys come from?

SnapTrade's model: an *app* = `client_id` + `consumer_key` (a backend secret); each end user is
a *connected user* = `user_id` + `user_secret`. SnapTrade is explicit that the `consumerKey`
**must never be embedded in a client-side/desktop app** — signature auth is meant to run from a
server. Free tier = 5 connections; paid = $1.50/connected-user/month.

**Chosen model: Bring-Your-Own keys, with guardrails.** Each user creates a free SnapTrade
account, makes an app, and pastes their own `client_id` + `consumer_key` into the Integrations
tab (stored in the OS keyring like the Anthropic key). A "Connect Robinhood" button then runs
the link flow. This is secure (each user's key lives only on their own machine, never shipped),
matches the app's existing BYO pattern (Anthropic key, Gmail app password), and is shippable
now. Cost: a ~3-minute one-time signup, softened by an inline explainer + "how to get your
keys" wizard.

Rejected:
- **Bundle the developer key** in the `.exe` — best UX but violates SnapTrade's security
  guidance (extractable key), shares a 5-connection free tier across all users, and makes a
  leaked key the owner's liability. A Band-Aid with a hard ceiling.
- **Cloud backend now** — the proper "big dogs" SaaS answer (server holds the key, zero user
  signup) but a whole backend + hosting to build/run. Deferred to a future phase (see seam).

## Architecture & the SaaS seam

One new module, `src/brokerage_link.py`, owns the connect lifecycle and exposes exactly four
functions. The UI and routes call **only** these four:

- `save_keys(client_id, consumer_key)` — persist the user's SnapTrade app keys
- `start_connect()` -> portal URL — register the connected user if needed, return the
  SnapTrade portal redirect URL
- `check_connection()` -> `{connected: bool, account_count: int}` — poll SnapTrade for linked
  accounts
- `disconnect()` — clear stored brokerage creds

Today these are implemented against SnapTrade directly using the user's BYO keys. **SaaS upgrade
path:** write a second implementation of the same four functions that calls a hosted backend
(which holds the `consumer_key`); select it via a config flag and hide the key-entry fields.
UI, routes, and the daily briefing are unchanged. That is the "seamless later" guarantee.

The actual holdings sync after the link is established is the **existing** `src/broker.py`,
untouched. `brokerage_link.py` is only about *establishing* the link; `broker.py` is about
*reading* holdings.

## UX: new "Brokerage (Robinhood)" section in the Integrations tab

Matches existing AI/Email block styling (vanilla JS in `ui/`, `field`/`row`/`muted`/`msg`
classes; status spans; write-only secret inputs).

1. **Plain-English explainer (always visible):** what SnapTrade is; the connection is
   **read-only** (the app can never place trades); no Robinhood password is stored; 2FA happens
   once at link time. Plus one honest line on **why you enter your own keys for now** so the BYO
   step reads as intentional, not busywork.
2. **Collapsible "How to get your free keys":** numbered steps — create a free SnapTrade
   account -> create an app -> copy Client ID + Consumer Key -> paste below. Includes the
   SnapTrade dashboard link.
3. **Two fields + Save:** Client ID (visible text) and Consumer Key (password field,
   write-only).
4. **`Connect Robinhood` button:** opens the SnapTrade portal in a new tab; the UI auto-checks
   every ~3s and flips to **"Connected ✓ — N holdings"** when SnapTrade reports the account. A
   manual "Check connection" button is the fallback.
5. **Disconnect button:** clears all stored brokerage creds and resets status.

## Secrets & storage (mirrors the existing email pattern)

- `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_USER_ID` -> `integrations.yaml` (non-secret; returned to the
  UI so the user can confirm them). Extend `config.INTEGRATION_FIELDS` + `load_integrations` /
  `save_integrations`.
- `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_USER_SECRET` -> OS keyring, write-only, never returned.
  Add both to `secrets_store.SECRET_KEYS`.

Because `profile.EnvSecrets.apply_to_environ()` already pushes keyring `SECRET_KEYS` and
`INTEGRATION_FIELDS` into `os.environ`, `broker.is_configured()` lights up automatically once
all four are present — **no engine changes** and no `.env` editing.

## Routes (extend `src/routes_integrations.py`)

- `GET /api/integrations` — add a `brokerage` block:
  `{client_id, keys_set: bool, connected: bool, account_count: int}` (consumer_key/user_secret
  never returned).
- `PUT /api/integrations/brokerage/keys` — save `client_id` (config) + `consumer_key` (keyring).
  Refresh the live profile so the same session can connect without restart.
- `POST /api/integrations/brokerage/connect` — `brokerage_link.start_connect()`; return
  `{redirect_url}`.
- `POST /api/integrations/brokerage/verify` — `brokerage_link.check_connection()`; return
  `{connected, account_count}`.
- `POST /api/integrations/brokerage/disconnect` — `brokerage_link.disconnect()`.

## Data flow (connect)

1. User pastes Client ID + Consumer Key -> Save (consumer_key -> keyring, client_id -> config).
2. Click Connect -> server registers the SnapTrade connected user (persists `user_id` ->
   config, `user_secret` -> keyring) and returns the portal URL.
3. UI opens the portal in a new tab; user logs into Robinhood and authorizes.
4. UI polls `verify` (~3s cadence); server calls SnapTrade `list_user_accounts`; on success ->
   "Connected ✓ — N holdings".
5. Next briefing auto-syncs through the existing `broker.resolve_positions` path.

## Error handling

- Missing keys -> 400 "enter your Client ID and Consumer Key first".
- Register/login fails (bad keys) -> map SnapTrade error to "check your keys".
- Free-tier 5-connection cap reached -> surface that explicitly.
- Not finished in portal yet -> "finish in the browser, then click Check connection".
- All secrets write-only (status reports set/not-set only), consistent with AI/email.
- The briefing already degrades to `positions.yaml` on any sync failure, so a bad/partial link
  never breaks the daily run.

## Testing

- Unit-test `brokerage_link` against a **fake SnapTrade client** (same seam style as the
  existing `tests/test_broker.py`): register returns a `userSecret`, login returns a
  `redirectURI`, `list_user_accounts` returns accounts. Assert persistence calls (keyring +
  config) and the status logic. No network.
- Route tests over a **temp profile + fake keyring backend** (existing pattern in the suite):
  save keys -> connect -> verify -> disconnect, asserting secrets are never returned in
  responses.

## Bonus fix folded in

Switch `broker._default_list_positions` from the deprecated
`account_information.get_user_account_positions` to SnapTrade's current holdings endpoint
(removes the deprecation warning observed during setup). Verify the response shape still parses
in `broker._extract_ticker` / `broker._aggregate`; adjust the parser only if the field paths
changed.

## Scope / non-goals

- No cloud backend in this phase (seam leaves the door open).
- No change to the owner's repo/CLI profile behavior (`Profile.for_repo` stays keyring-disabled;
  the owner keeps using `.env`). The button serves the per-user `%APPDATA%` profile.
- Robinhood is the named broker for copy, but the SnapTrade flow is broker-agnostic; no
  Robinhood-specific code.
