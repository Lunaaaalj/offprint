"""Shared test helpers."""

import os
from collections.abc import Callable
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
