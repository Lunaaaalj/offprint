"""Tests for the `fixtures` helper."""

from collections.abc import Callable
from pathlib import Path

import pytest


def test_finds_a_fixture_by_slug(fixtures: Callable[[str], Path]) -> None:
    assert (fixtures("frontiers-frai-2026-1748985") / "paper.pdf").is_file()


def test_missing_fixture_names_the_slug(fixtures: Callable[[str], Path]) -> None:
    with pytest.raises(FileNotFoundError, match="no-such-paper"):
        fixtures("no-such-paper")
