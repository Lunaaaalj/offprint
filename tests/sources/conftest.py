"""Keep the resolver tests off the network and out of the real home directory."""

import socket
from collections.abc import Callable
from pathlib import Path

import pytest
from replay_support import CONTACT, Replay

from offprint.sources import Config


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No real home, no real config, no contact address and no sockets."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a test tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(tmp_path / "no-such-config.toml"))
    monkeypatch.delenv("OFFPRINT_CONTACT_EMAIL", raising=False)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(cache_dir=tmp_path / "cache", contact=CONTACT)


@pytest.fixture
def replay() -> Callable[[str], Replay]:
    return Replay
