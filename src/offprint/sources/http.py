"""The resolver's only door to the network: a polite, rate-limited HTTP client.

httpx is used over urllib for its timeouts per phase, redirect limits and `MockTransport`, which
lets tests replay recorded responses through the real client with no extra test dependency.
"""

import json
import time
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from offprint import __version__
from offprint.sources.errors import FetchError

PROJECT_URL = "https://github.com/Lunaaaalj/offprint"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_MAX_REDIRECTS = 5
_DEFAULT_INTERVAL = 1.0
# Seconds between requests to one host, for hosts that publish a limit.
_HOST_INTERVALS = {
    "export.arxiv.org": 3.0,  # arXiv API terms: one request every three seconds.
    "arxiv.org": 3.0,
    "api.crossref.org": 0.2,
}


def user_agent(contact: str | None) -> str:
    who = f"mailto:{contact}" if contact else PROJECT_URL
    return f"offprint/{__version__} ({who})"


class RateLimiter:
    """Spaces out requests per host. The clock is injected so tests never really wait."""

    def __init__(
        self,
        intervals: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._intervals = _HOST_INTERVALS if intervals is None else intervals
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            remaining = last + self._intervals.get(host, _DEFAULT_INTERVAL) - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()


class Http:
    """GET requests with a user agent, a timeout, a rate limit and a clear error per failure."""

    def __init__(
        self,
        contact: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._limiter = limiter or RateLimiter()
        self._client = httpx.Client(
            headers={"User-Agent": user_agent(contact)},
            timeout=_TIMEOUT,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            transport=transport,
        )

    def __enter__(self) -> "Http":
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def get_json(self, url: str) -> Any:
        body = self.get_bytes(url)
        try:
            return json.loads(body)
        except ValueError:
            raise FetchError(f"{_host(url)} returned something that isn't JSON") from None

    def get_bytes(self, url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
        """Return the body of `url`, or raise `FetchError`."""
        host = _host(url)
        if urlsplit(url).scheme not in ("http", "https"):
            raise FetchError(f"refusing to fetch {url!r}: not an http(s) URL")
        self._limiter.wait(host)
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise FetchError(
                        f"{host} answered HTTP {response.status_code}", response.status_code
                    )
                return _read_capped(response.iter_bytes(), limit, host)
        except httpx.TimeoutException:
            raise FetchError(f"{host} timed out") from None
        except httpx.TooManyRedirects:
            raise FetchError(f"{host} redirected too many times") from None
        except httpx.HTTPError as error:
            raise FetchError(f"couldn't reach {host}: {error}") from None
        except httpx.InvalidURL as error:
            raise FetchError(f"invalid URL {url!r}: {error}") from None


def _read_capped(chunks: Iterable[bytes], limit: int, host: str) -> bytes:
    body = bytearray()
    for chunk in chunks:
        body.extend(chunk)
        if len(body) > limit:
            raise FetchError(f"{host} sent more than {limit} bytes, gave up")
    return bytes(body)


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or url
    except ValueError:
        return url
