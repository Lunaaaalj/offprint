"""The recordings are checked in, so check they hold nothing that shouldn't be public."""

import gzip
import io
import json
import re
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from replay_support import CONTACT, RECORDINGS

SCENARIOS = sorted(path for path in RECORDINGS.iterdir() if path.is_dir())
ALLOWED_HEADERS = {"content-type", "location", "retry-after"}
ALLOWED_EMAILS = {CONTACT.encode(), b"redacted@example.com"}
_EMAIL = re.compile(rb"[\w.+-]+\\?@[\w-]+\.[\w.-]*\w")
_SECRET = re.compile(
    rb"(?i)set-cookie|authorization: |api[_-]?key=|access[_-]?token|bearer [a-z0-9]|ghp_[a-z0-9]"
)


def _exchanges(scenario: Path) -> list[dict[str, object]]:
    text = (scenario / "exchanges.json").read_text(encoding="utf-8")
    return json.loads(text)["exchanges"]


def _texts(path: Path) -> Iterator[bytes]:
    """The bytes of a body, looking inside gzip and tar."""
    body = path.read_bytes()
    if not body.startswith(b"\x1f\x8b"):
        yield body
        return
    plain = gzip.decompress(body)
    if plain[257:262] != b"ustar":
        yield plain
        return
    with tarfile.open(fileobj=io.BytesIO(plain)) as archive:
        for member in archive.getmembers():
            handle = archive.extractfile(member)
            if handle:
                yield handle.read()


def test_every_scenario_is_labelled_real() -> None:
    assert len(SCENARIOS) >= 3
    for scenario in SCENARIOS:
        recording = json.loads((scenario / "exchanges.json").read_text(encoding="utf-8"))
        assert recording["synthetic"] is False
        assert recording["recorded"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.name)
def test_only_allow_listed_headers_are_kept(scenario: Path) -> None:
    for exchange in _exchanges(scenario):
        headers = exchange["headers"]
        assert isinstance(headers, dict)
        assert {name.lower() for name in headers} <= ALLOWED_HEADERS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.name)
def test_urls_carry_only_the_placeholder_contact(scenario: Path) -> None:
    text = (scenario / "exchanges.json").read_bytes().replace(b"%40", b"@")
    assert set(_EMAIL.findall(text)) <= ALLOWED_EMAILS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.name)
def test_bodies_hold_no_addresses_or_secrets(scenario: Path) -> None:
    for path in sorted(scenario.glob("*.body")):
        for text in _texts(path):
            assert set(_EMAIL.findall(text)) <= ALLOWED_EMAILS, path
            assert _SECRET.search(text) is None, path


def test_the_contact_is_not_hard_coded_in_the_package() -> None:
    source = Path(__file__).parents[2] / "src" / "offprint" / "sources"
    for path in source.glob("*.py"):
        assert _EMAIL.search(path.read_bytes()) is None, path
