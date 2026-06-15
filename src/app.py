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
    print(f"Stock Advisor running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
