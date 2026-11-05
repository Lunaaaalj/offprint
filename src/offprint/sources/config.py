"""Resolver settings: the contact address and the cache directory.

The contact address comes from `OFFPRINT_CONTACT_EMAIL`, or from `contact_email` in
`~/.config/offprint/config.toml` (`OFFPRINT_CONFIG_FILE` overrides that path). There is no
default: APIs are told who is calling only if the user chose to say so.

The cache lives in `~/.cache/offprint/`, unless `OFFPRINT_CACHE_DIR` says otherwise.
"""

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from offprint.sources.errors import ConfigError

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True, slots=True)
class Config:
    cache_dir: Path
    contact: str | None = None


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Read the settings from the environment and the config file."""
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    path = Path(env.get("OFFPRINT_CONFIG_FILE") or home / ".config" / "offprint" / "config.toml")
    cache_dir = Path(env.get("OFFPRINT_CACHE_DIR") or home / ".cache" / "offprint")

    contact = env.get("OFFPRINT_CONTACT_EMAIL") or _read_file_contact(path)
    if contact is not None and not _EMAIL.fullmatch(contact):
        raise ConfigError(f"the contact address {contact!r} isn't an email address")
    return Config(cache_dir=cache_dir, contact=contact)


def _read_file_contact(path: Path) -> str | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"can't read {path}: {error}") from error
    contact = data.get("contact_email")
    if contact is not None and not isinstance(contact, str):
        raise ConfigError(f"contact_email in {path} must be a string")
    return contact
