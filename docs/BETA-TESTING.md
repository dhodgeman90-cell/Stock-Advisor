# Stock Advisor — Beta Tester Quick Start

Thanks for testing **Stock Advisor**! It's a small app that runs on your own computer and
gives you a daily stock-market briefing — buy candidates, sell signals, and (optionally) your
own holdings. It **only suggests; it never buys or sells anything.**

This guide gets you from "I got a link" to "I'm reading my first briefing" in about 5 minutes.

---

> ## ⚠️ READ THIS FIRST: Windows will warn you — that's expected
>
> When you download and run this, **Windows (and maybe your browser or antivirus) will say
> something like "Windows protected your PC" or "this file could harm your computer."**
>
> **This is NOT because the app is dangerous.** It happens because the app isn't
> *code-signed* yet — code signing is a paid certificate the developer hasn't purchased during
> this early beta. Any unsigned app from a small developer triggers this same warning, even
> completely safe ones. Microsoft is essentially saying *"we don't recognize this publisher
> yet,"* not *"this is malware."*
>
> **You will need to click through the warning on purpose** (exact steps below). If you're not
> comfortable doing that, that's completely fine — just let me know and we'll wait until the app
> is signed.

---

## What you'll need
- A **Windows 10 or 11** PC.
- About **150 MB** of free disk space.
- ~5 minutes. **No admin password required** (it installs just for your user account).

---

## Step 1 — Download it
1. Open the **download link I sent you** (Google Drive / Dropbox / OneDrive).
2. Download **`StockAdvisor-Setup-x.y.z.exe`** (the version number may differ).
3. Your browser may say *"This file isn't commonly downloaded"* or *"could harm your
   computer."* Choose **Keep** / **Keep anyway**. *(See the warning box above — this is the
   unsigned-app warning, expected.)*

## Step 2 — Install it
1. Double-click the downloaded **`StockAdvisor-Setup-x.y.z.exe`**.
2. Windows SmartScreen may show a blue box: **"Windows protected your PC."**
   - Click **More info** (small link in the box).
   - Then click the **Run anyway** button that appears.
3. The installer opens. Click through it (Next → Install → Finish). It installs only for you —
   no admin prompt.
4. Optionally let it create a **desktop shortcut**.

## Step 3 — Open it
- Launch **Stock Advisor** from the Start Menu (or the desktop shortcut).
- A small app window opens. The **first time**, you'll see a short disclaimer — read it and
  click **"I understand — continue."**

## Step 4 — Run your first briefing
1. On the **Briefing** screen, pick a **Strategy** with the slider (Balanced is a fine start).
2. Click **Run now**.
3. Give it ~30 seconds (it's fetching live market data). Your briefing appears.

That's it — you're running. **Everything below is optional.**

---

## Optional extras (skip any or all)
The app works fully on built-in rules with **none** of these. Add them only if you want to:

- **AI analysis** — paste your own Anthropic API key in the **Integrations** tab to turn on
  the AI commentary on active days.
- **Email the briefing to yourself** — add a Gmail address + app password in **Integrations**.
- **Live holdings from your brokerage** — in **Integrations → Brokerage**, connect through
  SnapTrade (a free account, ~3 minutes). Your real positions then show up automatically. If
  you skip this, you can still type positions in by hand on the **Positions** tab.

---

## Your privacy
- The app runs **entirely on your computer** (a local web page at `127.0.0.1`). **Nothing is
  sent to the developer.**
- Your settings and data live in your own user folder (`%APPDATA%\StockAdvisor`).
- The only exception is the optional brokerage feature, which talks to **your own** SnapTrade
  account — not to me.

## Getting updates
When there's a new version, I'll send you a new installer. Just run it the same way — **your
settings and data carry over** automatically.

## If something breaks 🐛
Please tell me! It's hugely helpful if you include the log file:
1. Press **Windows key + R**, paste this, and press Enter:
   `%APPDATA%\StockAdvisor\logs`
2. Send me the **`app.log`** file from that folder, plus a quick note on what you clicked and
   what happened.

## Uninstalling
**Settings → Apps → Installed apps → Stock Advisor → Uninstall.** (Your saved data in
`%APPDATA%\StockAdvisor` stays unless you delete that folder yourself.)

---

> ## 💵 Important: this is information, not financial advice
> Stock Advisor summarizes public market data and rule-based signals to help you do your own
> research. **It is not financial advice, and it never places trades.** Every buy/sell decision
> is yours. Markets carry risk; you can lose money. Please don't treat any briefing as a
> recommendation to act.

Thanks again for helping test — your feedback (what's confusing, what's useful, what breaks) is
exactly what this beta is for.
