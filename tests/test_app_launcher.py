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
