"""Launcher / process entry point for the local Stock Advisor app.

`python -m src.app` resolves this machine's profile (%APPDATA%\\StockAdvisor),
seeds first-run defaults, starts the FastAPI server on 127.0.0.1 (loopback only —
never network-exposed), and opens the default browser. The packaged build runs this.
"""
from __future__ import annotations

import socket
import threading
import webbrowser

from src import onboarding, server
from src.apppaths import user_base_dir
from src.profile import Profile

PREFERRED_PORT = 8765


def build_profile() -> Profile:
    return Profile.for_base(user_base_dir())


def find_free_port(preferred: int = PREFERRED_PORT, tries: int = 50) -> int:
    """Return the first free loopback port at or after `preferred`."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:   # nonzero == nothing listening
                return port
    return preferred


def main(open_browser: bool = True) -> None:
    import uvicorn

    profile = build_profile()
    onboarding.seed_profile(profile)
    app = server.create_app(profile)
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    bar = "=" * 60
    print(f"\n{bar}\n  Stock Advisor is running at:  {url}\n"
          f"  If your browser doesn't open, copy that address into it.\n"
          f"  Keep this window open — press Ctrl+C here to stop.\n{bar}\n")
    if open_browser:
        def _open() -> None:
            # webbrowser.open returns False when no handler is found; tell the
            # user the address instead of leaving them at a silent console.
            if not webbrowser.open(url):
                print(f"  Couldn't open a browser automatically — go to {url}")
        threading.Timer(1.0, _open).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
