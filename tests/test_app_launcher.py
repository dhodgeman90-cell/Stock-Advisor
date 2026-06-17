import socket

from src import app as launcher
from src.profile import Profile


def test_build_profile_uses_user_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_ADVISOR_HOME", str(tmp_path / "home"))
    profile = launcher.build_profile()
    assert isinstance(profile, Profile)
    assert profile.config_dir == tmp_path / "home" / "config"


def test_find_free_port_returns_an_unused_port():
    port = launcher.find_free_port(preferred=8765)
    # nothing should be listening on the returned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        assert s.connect_ex(("127.0.0.1", port)) != 0


def test_find_free_port_skips_a_busy_port():
    # occupy a port, then confirm find_free_port hands back a different one
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        port = launcher.find_free_port(preferred=taken)
        assert port != taken


def test_find_app_browser_returns_first_existing():
    second = launcher._BROWSER_CANDIDATES[1]
    found = launcher._find_app_browser(exists=lambda p: p == second)
    assert found == second


def test_find_app_browser_none_when_no_browser():
    assert launcher._find_app_browser(exists=lambda p: False) is None


def test_app_window_args_are_chromeless_and_sized():
    args = launcher._app_window_args("msedge.exe", "http://127.0.0.1:8765", "C:\\tmp\\win")
    assert args[0] == "msedge.exe"
    assert "--app=http://127.0.0.1:8765" in args          # chromeless app window
    assert f"--window-size={launcher.WINDOW_SIZE}" in args  # sized, not maximized
    assert "--user-data-dir=C:\\tmp\\win" in args          # dedicated instance


def test_should_quit_waits_through_startup_before_first_ping():
    # No ping yet, still inside the startup grace -> keep running.
    assert launcher._should_quit(None, now=10.0, started=0.0,
                                 startup_grace=30.0, idle_grace=6.0) is False
    # No ping and startup grace elapsed -> the UI never connected, quit.
    assert launcher._should_quit(None, now=31.0, started=0.0,
                                 startup_grace=30.0, idle_grace=6.0) is True


def test_should_quit_when_heartbeats_stop():
    # Recent ping -> window is open, keep running.
    assert launcher._should_quit(100.0, now=103.0, started=0.0,
                                 startup_grace=30.0, idle_grace=6.0) is False
    # Pings went silent past the idle grace -> window closed, quit.
    assert launcher._should_quit(100.0, now=110.0, started=0.0,
                                 startup_grace=30.0, idle_grace=6.0) is True
