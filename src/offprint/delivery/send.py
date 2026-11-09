"""Send a book to the Kindle: check it, fit it under the size limit, send it, log it.

Order of the steps: the QA verdict, the duplicate check, the size, then the email. Nothing is
written to the log unless an email was attempted.
"""

import hashlib
import json
import smtplib
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

from offprint.delivery import log
from offprint.delivery.config import DeliveryConfig, smtp_password
from offprint.delivery.errors import DeliveryError, VerdictBlocked
from offprint.delivery.message import build_message
from offprint.delivery.shrink import shrink_epub
from offprint.qa.book import BookError, read_package_meta

_TIMEOUT = 60
SmtpFactory = Callable[[DeliveryConfig], smtplib.SMTP]


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    result: Literal["sent", "dry-run"]
    to: str
    message_bytes: int
    shrunk_to: int | None = None
    """The width the images were downscaled to, if the book was over the limit."""
    eml: Path | None = None


def read_verdict(epub: Path, qa: Path | None = None) -> str | None:
    """The verdict in the book's `.qa.json`, or None if there is no report to read."""
    path = qa or epub.with_suffix(".qa.json")
    try:
        verdict = json.loads(path.read_text(encoding="utf-8")).get("verdict")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as error:
        raise DeliveryError(f"can't read the QA report {path}: {error}") from error
    return verdict if isinstance(verdict, str) else None


def deliver(
    epub: Path,
    config: DeliveryConfig,
    *,
    verdict: str | None,
    force: bool = False,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    smtp_factory: SmtpFactory | None = None,
    keyring_get: Callable[[str, str], str | None] | None = None,
) -> Delivery:
    """Send `epub` to the Kindle address, or with `dry_run` write the `.eml` next to it."""
    if verdict != "pass" and not force:
        raise VerdictBlocked(
            f"{epub.name} isn't sent: its QA verdict is {verdict or 'unknown (no .qa.json)'}. "
            "Fix it, or send it anyway with --force."
        )
    try:
        meta = read_package_meta(epub)
        digest = hashlib.sha256(epub.read_bytes()).hexdigest()
    except (BookError, OSError) as error:
        raise DeliveryError(str(error)) from error
    earlier = log.already_sent(config.log_path, meta.identifier, digest)
    if earlier is not None and not force:
        raise DeliveryError(
            f"{epub.name} was already sent on {earlier.time} to {earlier.to}. "
            "Send it again with --force."
        )

    message, width = _fit(epub, meta.title, config)
    size = len(message.as_bytes())
    if dry_run:
        eml = epub.with_suffix(".eml")
        eml.write_bytes(message.as_bytes())
        return Delivery(
            result="dry-run", to=config.kindle, message_bytes=size, shrunk_to=width, eml=eml
        )
    _send(message, config, env, smtp_factory, keyring_get, epub, meta.identifier, digest)
    return Delivery(result="sent", to=config.kindle, message_bytes=size, shrunk_to=width)


def _fit(epub: Path, title: str, config: DeliveryConfig) -> tuple[EmailMessage, int | None]:
    """The email for `epub`, with its images downscaled until it fits, or an error.

    The limit applies to the encoded email, which is a third larger than the file: base64 turns
    3 bytes into 4.
    """

    def build(path: Path) -> EmailMessage:
        return build_message(
            path.read_bytes(),
            filename=epub.name,
            sender=config.sender,
            to=config.kindle,
            title=title,
        )

    message = build(epub)
    if len(message.as_bytes()) <= config.max_bytes:
        return message, None
    smallest = len(message.as_bytes())
    with tempfile.TemporaryDirectory() as work:
        for width in config.widths:
            shrunk = shrink_epub(epub, Path(work) / epub.name, width)
            message = build(shrunk)
            smallest = min(smallest, len(message.as_bytes()))
            if len(message.as_bytes()) <= config.max_bytes:
                return message, width
    limit = config.max_bytes / 1e6
    raise DeliveryError(
        f"{epub.name} is {smallest / 1e6:.1f} MB as an email, over the {limit:.0f} MB limit, "
        f"even with images downscaled to {min(config.widths, default=0)} px"
    )


def _send(
    message: EmailMessage,
    config: DeliveryConfig,
    env: Mapping[str, str] | None,
    smtp_factory: SmtpFactory | None,
    keyring_get: Callable[[str, str], str | None] | None,
    epub: Path,
    identifier: str,
    digest: str,
) -> None:
    password = smtp_password(config, env, keyring_get)

    def record(result: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        entry = log.Record(
            identifier=identifier, sha256=digest, time=stamp, result=result, to=config.kindle
        )
        log.append(config.log_path, entry)

    try:
        with (smtp_factory or _connect)(config) as server:
            if config.security == "starttls":
                server.starttls()
            if config.username is not None and password is not None:
                server.login(config.username, password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        record(f"failed: {error}")
        raise DeliveryError(f"{epub.name} wasn't sent: {error}") from error
    record("sent")


def _connect(config: DeliveryConfig) -> smtplib.SMTP:
    if config.security == "ssl":
        return smtplib.SMTP_SSL(config.host, config.port, timeout=_TIMEOUT)
    return smtplib.SMTP(config.host, config.port, timeout=_TIMEOUT)
