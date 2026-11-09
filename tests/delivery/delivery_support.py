"""Helpers shared by the delivery tests."""

import io
import os
import socket
from dataclasses import dataclass, field

from PIL import Image


def noise_png(width: int, height: int) -> bytes:
    """A PNG that doesn't compress, so its size follows its pixel count."""
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@dataclass
class Inbox:
    host: str
    port: int
    envelopes: list = field(default_factory=list)


class _Capture:
    def __init__(self, inbox: Inbox) -> None:
        self.inbox = inbox

    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802 (aiosmtpd's name)
        self.inbox.envelopes.append(envelope)
        return "250 Message accepted"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
