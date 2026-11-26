"""Shared test helpers."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from offprint.browser import BrowserUnavailableError, chromium_page

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Callable[[str], Path]:
    """Return a function that finds `tests/fixtures/<slug>/`, failing clearly if it's missing."""

    def find(slug: str) -> Path:
        path = FIXTURES_DIR / slug
        if not path.is_dir():
            available = ", ".join(sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir()))
            raise FileNotFoundError(f"no fixture {slug!r} (available: {available})")
        return path

    return find


def _isolate(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(root / "cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(root / "no-such-config.toml"))
    monkeypatch.delenv("OFFPRINT_CONTACT_EMAIL", raising=False)


@pytest.fixture(scope="session", autouse=True)
def isolated_session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep module- and session-scoped fixtures off the real cache and config too.

    They are set up before any function-scoped fixture, so `isolated_test` comes too late for them.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        _isolate(monkeypatch, tmp_path_factory.mktemp("offprint-home"))
        yield


@pytest.fixture(autouse=True)
def isolated_test(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test reads or writes the real `~/.cache/offprint` or `~/.config/offprint`."""
    _isolate(monkeypatch, tmp_path)


@pytest.fixture(scope="session")
def chromium() -> None:
    """Skip a test when Chromium is missing locally. In CI that's a failure, not a skip."""
    try:
        with chromium_page(16, 16):
            pass
    except BrowserUnavailableError as error:
        if os.environ.get("CI"):
            pytest.fail(f"Chromium must be installed in CI: {error}")
        pytest.skip(f"Chromium isn't installed: {error}")
