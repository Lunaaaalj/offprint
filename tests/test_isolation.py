"""The suite never reads the real `~/.cache/offprint` or `~/.config/offprint` (conftest.py)."""

import os
from pathlib import Path

import pytest

from offprint.sources import load_config


@pytest.fixture(scope="module")
def module_paths() -> tuple[Path, Path]:
    return Path(os.environ["OFFPRINT_CACHE_DIR"]), Path(os.environ["OFFPRINT_CONFIG_FILE"])


def test_each_test_has_its_own_cache_and_no_config(tmp_path: Path) -> None:
    config = load_config()

    assert config.cache_dir.is_relative_to(tmp_path)
    assert not config.cache_dir.exists()
    assert config.contact is None


def test_module_fixtures_are_isolated_too(module_paths: tuple[Path, Path]) -> None:
    cache_dir, config_file = module_paths
    home = Path.home()

    assert not cache_dir.is_relative_to(home / ".cache")
    assert not config_file.is_relative_to(home / ".config")
    assert not config_file.exists()
