"""Delivery settings, from `~/.config/offprint/config.toml`.

```toml
[kindle]
address = "name_abc123@kindle.com"   # Manage Your Content and Devices > Preferences
sender = "me@example.com"            # must be on Amazon's Approved Personal Document E-mail List

[smtp]
host = "smtp.example.com"
port = 587                           # 587 for starttls, 465 for ssl, 25 for none
security = "starttls"                # or "ssl" or "none"
username = "me@example.com"          # leave out if the server needs no login

[limits]                             # all optional
max_mb = 50
widths = [1600, 1200, 900, 600]
```

The SMTP password is never in the file. It comes from `OFFPRINT_SMTP_PASSWORD`, or from the OS
keychain (`keyring set offprint USERNAME`).
"""

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from offprint.delivery.errors import DeliveryError

Security = Literal["starttls", "ssl", "none"]

KEYRING_SERVICE = "offprint"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PORTS: dict[str, int] = {"starttls": 587, "ssl": 465, "none": 25}
_SECURITY = tuple(_PORTS)
# Amazon accepts up to 50 MB per email. Its help pages disagree on whether that is per email or
# per attachment, so the limit applies to the whole encoded message, the stricter reading.
DEFAULT_MAX_MB = 50
DEFAULT_WIDTHS = (1600, 1200, 900, 600)
_MB = 1_000_000


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryConfig:
    kindle: str
    sender: str
    host: str
    port: int
    security: Security
    username: str | None
    max_bytes: int
    widths: tuple[int, ...]
    log_path: Path


def config_path(env: Mapping[str, str]) -> Path:
    home = Path(env.get("HOME") or Path.home())
    return Path(env.get("OFFPRINT_CONFIG_FILE") or home / ".config" / "offprint" / "config.toml")


def log_path(env: Mapping[str, str]) -> Path:
    if env.get("OFFPRINT_DELIVERY_LOG"):
        return Path(env["OFFPRINT_DELIVERY_LOG"])
    home = Path(env.get("HOME") or Path.home())
    data = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return data / "offprint" / "deliveries.jsonl"


def load_delivery_config(env: Mapping[str, str] | None = None) -> DeliveryConfig:
    """Read and check the delivery settings. Raises `DeliveryError` naming the key that is wrong."""
    env = os.environ if env is None else env
    path = config_path(env)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DeliveryError(
            f"no config file at {path}: add [kindle] and [smtp] sections (see docs/delivery.md)"
        ) from error
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DeliveryError(f"can't read {path}: {error}") from error

    kindle = _table(data, "kindle", path)
    smtp = _table(data, "smtp", path)
    limits = data.get("limits", {})
    if "password" in smtp:
        raise DeliveryError(
            f"{path}: the SMTP password can't be in the config file; "
            "use OFFPRINT_SMTP_PASSWORD or `keyring set offprint USERNAME`"
        )
    security = smtp.get("security", "starttls")
    if security not in _SECURITY:
        raise DeliveryError(f"{path}: smtp.security must be one of {list(_SECURITY)}")
    return DeliveryConfig(
        kindle=_email(kindle, "address", "kindle", path),
        sender=_email(kindle, "sender", "kindle", path),
        host=_text(smtp, "host", "smtp", path),
        port=_int(smtp, "port", "smtp", path, _PORTS[security]),
        security=security,
        username=_text(smtp, "username", "smtp", path, required=False),
        max_bytes=_int(limits, "max_mb", "limits", path, DEFAULT_MAX_MB) * _MB,
        widths=_widths(limits, path),
        log_path=log_path(env),
    )


def smtp_password(
    config: DeliveryConfig,
    env: Mapping[str, str] | None = None,
    keyring_get: Callable[[str, str], str | None] | None = None,
) -> str | None:
    """The SMTP password: from the environment, else the keychain. None if there is no login."""
    if config.username is None:
        return None
    env = os.environ if env is None else env
    password = env.get("OFFPRINT_SMTP_PASSWORD")
    if password:
        return password
    if keyring_get is None:
        import keyring

        keyring_get = keyring.get_password
    try:
        password = keyring_get(KEYRING_SERVICE, config.username)
    except Exception as error:  # keyring backends fail in many ways, none of them ours to handle
        raise DeliveryError(f"can't read the keychain: {error}") from error
    if not password:
        raise DeliveryError(
            f"no SMTP password for {config.username}: set OFFPRINT_SMTP_PASSWORD, "
            f"or run `keyring set {KEYRING_SERVICE} {config.username}`"
        )
    return password


def _table(data: Mapping[str, Any], name: str, path: Path) -> Mapping[str, Any]:
    table = data.get(name)
    if not isinstance(table, dict):
        raise DeliveryError(f"{path}: missing the [{name}] section")
    return table


def _text(
    table: Mapping[str, Any], key: str, section: str, path: Path, *, required: bool = True
) -> str | None:
    value = table.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeliveryError(f"{path}: {section}.{key} must be a non-empty string")
    return value.strip()


def _email(table: Mapping[str, Any], key: str, section: str, path: Path) -> str:
    value = _text(table, key, section, path)
    if value is None or not _EMAIL.fullmatch(value):
        raise DeliveryError(f"{path}: {section}.{key} {value!r} isn't an email address")
    return value


def _int(table: Mapping[str, Any], key: str, section: str, path: Path, default: int) -> int:
    value = table.get(key, default)
    if type(value) is not int or value <= 0:
        raise DeliveryError(f"{path}: {section}.{key} must be a positive integer")
    return value


def _widths(limits: Mapping[str, Any], path: Path) -> tuple[int, ...]:
    value = limits.get("widths", list(DEFAULT_WIDTHS))
    if not isinstance(value, list) or not all(type(w) is int and w > 0 for w in value):
        raise DeliveryError(f"{path}: limits.widths must be a list of positive integers")
    return tuple(sorted(set(value), reverse=True))
