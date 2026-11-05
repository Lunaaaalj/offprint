"""Config, the polite HTTP client, the sniffers and the cache layout."""

import gzip
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from replay_support import CONTACT, client

from offprint.sources import CacheError, ConfigError, Doi, FetchError, load_config
from offprint.sources import cache as cache_module
from offprint.sources.cache import entry_dir, entry_key
from offprint.sources.http import PROJECT_URL, RateLimiter, user_agent
from offprint.sources.sniff import classify_eprint, is_jats, is_pdf

# config


def test_contact_comes_from_the_environment() -> None:
    env = {"HOME": "/h", "OFFPRINT_CONTACT_EMAIL": CONTACT}
    assert load_config(env).contact == CONTACT


def test_contact_comes_from_the_config_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f'contact_email = "{CONTACT}"\n', encoding="utf-8")
    assert load_config({"HOME": "/h", "OFFPRINT_CONFIG_FILE": str(path)}).contact == CONTACT


def test_there_is_no_default_contact() -> None:
    assert load_config({"HOME": "/nonexistent"}).contact is None


def test_the_cache_defaults_to_the_home_directory_and_can_move() -> None:
    assert load_config({"HOME": "/h"}).cache_dir == Path("/h/.cache/offprint")
    env = {"HOME": "/h", "OFFPRINT_CACHE_DIR": "/elsewhere"}
    assert load_config(env).cache_dir == Path("/elsewhere")


@pytest.mark.parametrize("bad", ["nobody", "a@b", "a b@example.com", "x@example.com\r\nEvil: 1"])
def test_a_contact_that_could_corrupt_a_header_is_refused(bad: str) -> None:
    with pytest.raises(ConfigError, match="isn't an email"):
        load_config({"HOME": "/h", "OFFPRINT_CONTACT_EMAIL": bad})


def test_a_broken_config_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("not toml =", encoding="utf-8")
    with pytest.raises(ConfigError, match="can't read"):
        load_config({"HOME": "/h", "OFFPRINT_CONFIG_FILE": str(path)})


# http


def test_user_agent_names_the_contact_only_if_there_is_one() -> None:
    assert user_agent(CONTACT).endswith(f"(mailto:{CONTACT})")
    assert user_agent(None).endswith(f"({PROJECT_URL})")


def test_requests_carry_the_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ok")

    with client(httpx.MockTransport(handler)) as http:
        http.get_bytes("https://api.example.com/x")
    assert CONTACT in seen[0].headers["user-agent"]


@dataclass
class FakeTime:
    now: float = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_rate_limiter_spaces_requests_per_host() -> None:
    time = FakeTime()
    limiter = RateLimiter({"a.example": 3.0}, clock=time.clock, sleep=time.sleep)

    limiter.wait("a.example")
    assert time.now == 0
    limiter.wait("a.example")
    assert time.now == 3
    limiter.wait("b.example")  # another host doesn't wait
    assert time.now == 3
    time.now += 10
    limiter.wait("a.example")  # enough time has passed
    assert time.now == 13


def test_arxiv_gets_three_seconds_between_requests() -> None:
    time = FakeTime()
    limiter = RateLimiter(clock=time.clock, sleep=time.sleep)
    limiter.wait("export.arxiv.org")
    limiter.wait("export.arxiv.org")
    assert time.now == 3


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(503), "api.example.com answered HTTP 503"),
        (httpx.Response(404), "api.example.com answered HTTP 404"),
    ],
)
def test_bad_statuses_become_fetch_errors(response: httpx.Response, message: str) -> None:
    with client(httpx.MockTransport(lambda _: response)) as http:
        with pytest.raises(FetchError, match=message) as caught:
            http.get_bytes("https://api.example.com/x")
    assert caught.value.status == response.status_code


def test_timeouts_become_fetch_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with client(httpx.MockTransport(handler)) as http:
        with pytest.raises(FetchError, match="api.example.com timed out"):
            http.get_bytes("https://api.example.com/x")


def test_connection_failures_become_fetch_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with client(httpx.MockTransport(handler)) as http:
        with pytest.raises(FetchError, match="couldn't reach api.example.com"):
            http.get_bytes("https://api.example.com/x")


def test_redirect_loops_stop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    with client(httpx.MockTransport(handler)) as http:
        with pytest.raises(FetchError, match="redirected too many times"):
            http.get_bytes("https://api.example.com/x")


def test_oversized_downloads_are_abandoned() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 100))
    with client(transport) as http:
        with pytest.raises(FetchError, match="more than 10 bytes"):
            http.get_bytes("https://api.example.com/x", limit=10)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x.pdf"])
def test_only_http_urls_are_fetched(url: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be requested")

    with client(httpx.MockTransport(handler)) as http:
        with pytest.raises(FetchError, match="not an http"):
            http.get_bytes(url)


def test_non_json_is_reported() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"<html>"))
    with client(transport) as http:
        with pytest.raises(FetchError, match="isn't JSON"):
            http.get_json("https://api.example.com/x")


# sniffers


def _tar() -> bytes:
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w") as archive:
        info = tarfile.TarInfo("main.tex")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"tex"))
    return packed.getvalue()


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        (gzip.compress(_tar()), "tar.gz"),
        (_tar(), "tar"),
        (gzip.compress(rb"\documentclass{article}"), "tex.gz"),
        (b"%PDF-1.5 ...", "pdf"),
        (b"<html>rate limited</html>", "unknown"),
        (b"\x1f\x8bbroken", "unknown"),
        (b"", "unknown"),
    ],
)
def test_classify_eprint(body: bytes, kind: str) -> None:
    assert classify_eprint(body) == kind


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"<article><front/><body><p/></body></article>", True),
        (b'<?xml version="1.0"?>\n<!DOCTYPE article PUBLIC "x" "y">\n<article><body/></article>',
         True),
        (b'<!DOCTYPE pmc-articleset><pmc-articleset><article><body/></article></pmc-articleset>',
         True),
        (b"<article><front/></article>", False),
        (b"<html><body>a login page</body></html>", False),
        (b"<full-text-retrieval-response><body/></full-text-retrieval-response>", False),
        (b"", False),
    ],
)  # fmt: skip
def test_is_jats(body: bytes, expected: bool) -> None:
    assert is_jats(body) is expected


def test_is_pdf() -> None:
    assert is_pdf(b"%PDF-1.7\n")
    assert not is_pdf(b"<html>")


# cache layout


@pytest.mark.parametrize(
    "doi",
    [
        "10.1000/../../etc/passwd",
        "10.1000/../../../../../../tmp/evil",
        "10.1000/..",
        "10.1000//absolute",
        "10.1000/a\\b\\..\\..\\c",
        "10.1000/" + "a" * 5000,
        "10.1000/ünï¢ødé",
        "10.1000/CON",
    ],
)
def test_a_crafted_doi_stays_inside_the_cache(doi: str, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    path = entry_dir(root, Doi(doi))
    assert path.parent == root
    assert path.resolve().parent == root.resolve()
    assert len(path.name) < 255
    path.mkdir()  # a real filesystem accepts the name
    assert list(root.iterdir()) == [path]


def test_slugs_that_sanitise_alike_get_different_keys() -> None:
    assert entry_key(Doi("10.1000/a/b")) != entry_key(Doi("10.1000/a_b"))


def test_keys_are_readable() -> None:
    assert entry_key(Doi("10.3389/frai.2026.1748985")).startswith("doi-10.3389_frai.2026.1748985-")


@given(st.text(min_size=1, max_size=300))
def test_any_identifier_gives_a_safe_key(suffix: str) -> None:
    key = entry_key(Doi(f"10.1000/{suffix}"))
    assert "/" not in key and "\\" not in key and "\x00" not in key
    assert key not in (".", "..")
    assert key.isascii()
    assert len(key) < 255


def test_a_manifest_naming_another_file_is_refused(tmp_path: Path) -> None:
    from offprint.sources.model import Attempt, Resolution

    doi = Doi("10.1000/x")
    attempt = Attempt("pdf", "test", "chosen", "test")
    resolution = Resolution(str(doi), (attempt,), tier="pdf")
    with pytest.raises(CacheError, match="refusing to cache"):
        cache_module.store(tmp_path, doi, resolution, "../../evil.pdf", b"%PDF-")
