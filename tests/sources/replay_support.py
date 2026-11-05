"""Helpers for the resolver tests: replaying recordings through the real HTTP client."""

import json
from pathlib import Path
from typing import Any

import httpx

from offprint.sources.http import Http, RateLimiter

RECORDINGS = Path(__file__).parent.parent / "recordings"
CONTACT = "offprint-tests@example.com"


class Replay(httpx.BaseTransport):
    """Serves one recorded scenario. A request it doesn't hold fails the test."""

    def __init__(self, scenario: str) -> None:
        directory = RECORDINGS / scenario
        recording = json.loads((directory / "exchanges.json").read_text(encoding="utf-8"))
        self.synthetic: bool = recording["synthetic"]
        self.unused: list[dict[str, Any]] = list(recording["exchanges"])
        self.directory = directory
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for exchange in self.unused:
            if exchange["method"] == request.method and exchange["url"] == str(request.url):
                self.unused.remove(exchange)
                body = (self.directory / exchange["body"]).read_bytes()
                return httpx.Response(exchange["status"], headers=exchange["headers"], content=body)
        raise AssertionError(f"no recording for {request.method} {request.url}")


def no_wait() -> RateLimiter:
    return RateLimiter(sleep=lambda _: None)


def client(transport: httpx.BaseTransport, contact: str | None = CONTACT) -> Http:
    return Http(contact, transport=transport, limiter=no_wait())
