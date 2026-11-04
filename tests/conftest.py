"""Shared test helpers."""

from collections.abc import Callable
from pathlib import Path

import pytest

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
