"""Launcher / process entry point for the local Stock Advisor app.

`python -m src.app` resolves this machine's profile (%APPDATA%\\StockAdvisor),
seeds first-run defaults, starts the FastAPI server on 127.0.0.1 (loopback only —
never network-exposed), and opens the UI in a chromeless, sized **app window**
(Edge or Chrome in `--app` mode — no tabs, no address bar). Closing that window
quits the app.

The packaged build runs this with **no console window** (`console=False` in the
spec). In that mode sys.stdout/stderr are None, so they are redirected to
`%APPDATA%\\StockAdvisor\\logs\\app.log` — the app runs silently and testers still
have a log to send if something breaks.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

from src import onboarding, server
from src.apppaths import user_base_dir
from src.profile import Profile

PREFERRED_PORT = 8765
WINDOW_SIZE = "820,960"        # tidy app window: fits the 640px content with margins

# Chromium-based browsers support --app (chromeless window). Edge ships on every
# Win10/11 box, so this path almost always succeeds; Chrome is the fallback.
_BROWSER_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def build_profile() -> Profile:
    return Profile.for_base(user_base_dir())


def find_free_port(preferred: int = PREFERRED_PORT, tries: int = 50) -> int:
    """Return the first free loopback port at or after `preferred`."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:   # nonzero == nothing listening
                return port
    return preferred


def _redirect_std_streams() -> None:
    """A windowed (console=False) build has sys.stdout/stderr == None; any print or
    uvicorn log line would then crash. Point them at app.log so the app runs silently
    AND a tester has something to send when something goes wrong. No-op in dev (the
    console streams already exist)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    logs = user_base_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logf = open(logs / "app.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = logf
    if sys.stderr is None:
        sys.stderr = logf


def _find_app_browser(exists=os.path.exists):
    """Path to an Edge/Chrome executable for --app mode, or None if neither is found."""
    for path in _BROWSER_CANDIDATES:
        if exists(path):
            return path
    return None


def _app_window_args(browser: str, url: str, window_profile_dir: str) -> list:
    """Command line for a chromeless, sized app window.

    `--user-data-dir` forces a DEDICATED browser process — otherwise Edge/Chrome hand
    the URL to an already-running instance and return immediately, so we could not wait
    on the window. With a dedicated instance, closing the window ends this process and
    the app quits."""
    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={window_profile_dir}",
        f"--window-size={WINDOW_SIZE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _serve(app, port) -> None:
    """Run uvicorn WITHOUT installing signal handlers (we run it off the main thread,
    where signal handlers aren't allowed)."""
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    srv.install_signal_handlers = lambda: None
    srv.run()


def _wait_until_up(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)


def _serve_forever() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def _open_window(url: str) -> None:
    """Open the UI in a chromeless app window (Edge/Chrome) or, failing that, the
    default browser. We do NOT wait on the process: Chromium hands the URL to an
    already-running instance and returns immediately, so process lifetime is useless
    for detecting the window closing — the heartbeat watchdog owns that instead."""
    browser = _find_app_browser()
    if browser:
        import subprocess
        win_dir = os.path.join(os.environ.get("TEMP", os.getcwd()), "StockAdvisorWindow")
        subprocess.Popen(_app_window_args(browser, url, win_dir))
    else:
        webbrowser.open(url)


def _should_quit(last_ping, now, started, startup_grace, idle_grace) -> bool:
    """Quit decision for the heartbeat watchdog.

    Before any ping arrives, only quit if the UI never connected within startup_grace
    (e.g. the user closed the window before it loaded). Once pings have been seen, quit
    when they stop for idle_grace seconds (window closed)."""
    if last_ping is None:
        return (now - started) > startup_grace
    return (now - last_ping) > idle_grace


def _watchdog(app, *, poll: float = 2.0, startup_grace: float = 30.0,
              idle_grace: float = 6.0) -> None:
    """Block until the UI stops sending heartbeats, then return so the caller exits."""
    started = time.monotonic()
    while True:
        time.sleep(poll)
        if _should_quit(getattr(app.state, "last_ping", None),
                        time.monotonic(), started, startup_grace, idle_grace):
            return


def main(open_browser: bool = True) -> None:
    _redirect_std_streams()
    profile = build_profile()
    onboarding.seed_profile(profile)
    app = server.create_app(profile)
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Stock Advisor starting at {url}")

    # Server in a daemon thread; the main thread runs the heartbeat watchdog and owns
    # the app's lifetime. When the UI window closes, the heartbeat stops and we exit.
    threading.Thread(target=_serve, args=(app, port), daemon=True).start()
    _wait_until_up(port)

    if not open_browser:
        _serve_forever()       # dev/headless: serve until Ctrl+C
        return

    _open_window(url)
    _watchdog(app)             # returns once the UI window is gone
    os._exit(0)                # hard exit drops the daemon server thread immediately


if __name__ == "__main__":
    main()
