"""Fixtures for the delivery tests: a small EPUB, a config, and a fake SMTP server."""

import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from aiosmtpd.controller import Controller
from delivery_support import Inbox, _Capture, free_port, noise_png

from offprint.delivery import DeliveryConfig

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="pub-id">arxiv:2611.09197</dc:identifier>
<dc:title>Safe   Reinforcement
 Learning</dc:title></metadata>
<manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c"/></spine></package>"""

XHTML = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello</p></body></html>'


def write_epub(path: Path, *, image: tuple[int, int] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", OPF)
        archive.writestr("OEBPS/c.xhtml", XHTML)
        if image is not None:
            archive.writestr("OEBPS/images/figure.png", noise_png(*image))
    return path


@pytest.fixture
def epub(tmp_path: Path) -> Path:
    return write_epub(tmp_path / "paper.epub")


@pytest.fixture
def big_epub(tmp_path: Path) -> Path:
    """About 1.9 MB of image: 2.6 MB as an email, half that at half the width."""
    return write_epub(tmp_path / "big.epub", image=(1600, 400))


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., DeliveryConfig]:
    def make(**fields: object) -> DeliveryConfig:
        values: dict = {
            "kindle": "me_abc@kindle.com",
            "sender": "me@example.com",
            "host": "127.0.0.1",
            "port": 25,
            "security": "none",
            "username": None,
            "max_bytes": 50_000_000,
            "widths": (1600, 1200, 900, 600),
            "log_path": tmp_path / "data" / "deliveries.jsonl",
        }
        return DeliveryConfig(**{**values, **fields})

    return make


@pytest.fixture
def inbox() -> Iterator[Inbox]:
    """A real SMTP server on localhost that keeps what it receives."""
    box = Inbox(host="127.0.0.1", port=free_port())
    controller = Controller(_Capture(box), hostname=box.host, port=box.port)
    controller.start()
    try:
        yield box
    finally:
        controller.stop()
