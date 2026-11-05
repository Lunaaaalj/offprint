"""Re-record the HTTP responses the resolver tests replay. Needs network; never runs in CI.

    uv run python tests/recordings/record.py [SCENARIO ...]

The requests carry only the placeholder contact address. Only allow-listed response headers are
kept, and any other email address in a body (corresponding authors, in papers) is replaced. That
is the one change made to the responses, and each scenario's `exchanges.json` says so.
"""

import gzip
import io
import json
import re
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from offprint.sources import Config, resolve, sniff
from offprint.sources.http import Http

PLACEHOLDER_CONTACT = "offprint-tests@example.com"
REDACTED_EMAIL = b"redacted@example.com"
KEPT_HEADERS = frozenset({"content-type", "location", "retry-after"})
HERE = Path(__file__).parent
SCENARIOS = {
    # CC BY 4.0, no DOI or journal reference: tier 1.
    "arxiv-only": "2610.22829",
    # CC BY, a short editorial in PMC with no arXiv preprint: tier 2.
    "pmc-jats": "10.3389/fdmed.2025.1745526",
    # The golden fixture. Europe PMC answered HTTP 500, so PubMed Central's copy is used.
    "fixture-doi": "10.3389/frai.2026.1748985",
    # CC BY 4.0 on arXiv and at the publisher: a DOI that leads to tier 1 through arXiv's records.
    "doi-with-preprint": "10.1007/s00022-025-00782-5",
    # Well-formed identifiers that don't exist.
    "arxiv-missing": "2601.99999",
    "doi-missing": "10.3389/frai.2026.0000000",
}
_EMAIL = re.compile(rb"[\w.+-]+\\?@[\w-]+\.[\w.-]*\w")


class Recorder(httpx.BaseTransport):
    def __init__(self, directory: Path) -> None:
        self._inner = httpx.HTTPTransport()
        self._directory = directory
        self.exchanges: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        raw = httpx.Response(response.status_code, headers=response.headers, stream=response.stream)
        raw.read()
        headers = {k: v for k, v in response.headers.items() if k.lower() in KEPT_HEADERS}
        body = _scrub(raw.content)
        name = f"{len(self.exchanges):02d}.body"
        (self._directory / name).write_bytes(body)
        self.exchanges.append(
            {
                "method": request.method,
                "url": str(request.url),
                "status": response.status_code,
                "headers": headers,
                "body": name,
            }
        )
        return httpx.Response(response.status_code, headers=headers, content=raw.content)


def _scrub(body: bytes) -> bytes:
    if sniff.is_image(body):  # Compressed bytes can look like an address, and hold none.
        return body
    if body.startswith(b"\x1f\x8b"):
        return _scrub_gzip(body)
    return _EMAIL.sub(_replace_email, body)


def _replace_email(match: re.Match[bytes]) -> bytes:
    return match.group() if match.group() == PLACEHOLDER_CONTACT.encode() else REDACTED_EMAIL


def _scrub_gzip(body: bytes) -> bytes:
    plain = gzip.decompress(body)
    if plain[257:262] != b"ustar":
        return gzip.compress(_EMAIL.sub(_replace_email, plain), mtime=0)
    packed = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(plain)) as source,
        tarfile.open(fileobj=packed, mode="w") as target,
    ):
        for member in source.getmembers():
            handle = source.extractfile(member)
            data = _EMAIL.sub(_replace_email, handle.read()) if handle else b""
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
    return gzip.compress(packed.getvalue(), mtime=0)


def record(name: str) -> None:
    directory = HERE / name
    directory.mkdir(exist_ok=True)
    for old in directory.iterdir():
        old.unlink()
    recorder = Recorder(directory)
    with (
        tempfile.TemporaryDirectory() as cache,
        Http(PLACEHOLDER_CONTACT, transport=recorder) as http,
    ):
        config = Config(cache_dir=Path(cache), contact=PLACEHOLDER_CONTACT)
        result = resolve(SCENARIOS[name], config=config, http=http)
    payload = {
        "synthetic": False,
        "recorded": date.today().isoformat(),
        "input": SCENARIOS[name],
        "notes": "Real responses. Email addresses in bodies are replaced; nothing else changed.",
        "exchanges": recorder.exchanges,
    }
    text = json.dumps(payload, indent=2) + "\n"
    (directory / "exchanges.json").write_text(text, encoding="utf-8")
    print(name, result.tier, [(e["status"], e["url"]) for e in recorder.exchanges])


if __name__ == "__main__":
    for scenario in sys.argv[1:] or SCENARIOS:
        record(scenario)
