"""Fetching a JATS article's figures, caching them and reading them back offline."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from lxml import etree
from replay_support import Replay, client

from offprint.adapters.jats import graphic_name, graphic_refs, pmc_version
from offprint.sources import CacheError, Config, Doi, Resolution, cache, cached_source, resolve
from offprint.sources.graphics import (
    MediaFile,
    fetch_graphics,
    find_media,
    media_files,
    record_url,
)
from offprint.sources.sniff import is_image

JPEG = b"\xff\xd8\xff\xe0 a picture"
BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"
FIXTURE_DOI = "10.3389/frai.2026.1748985"
DOI = Doi("10.1234/x")


def article(*hrefs: str, ids: str = '<article-id pub-id-type="pmcid-ver">PMC1.2</article-id>'):
    figures = "".join(f'<fig><graphic xlink:href="{href}"/></fig>' for href in hrefs)
    return (
        '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>'
        f"{ids}</article-meta></front><body>{figures}</body></article>"
    ).encode()


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def serve(responses: dict[str, tuple[int, bytes]]):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url not in responses:
            raise AssertionError(f"unexpected request: {url}")
        status, body = responses[url]
        return httpx.Response(status, content=body)

    return client(httpx.MockTransport(handler)), requested


def record(*names: str, body: bytes = JPEG) -> bytes:
    media = [f"s3://pmc-oa-opendata/PMC1.2/{name}?md5={md5(body)}" for name in names]
    return json.dumps({"media_urls": media}).encode()


RECORD = f"{BUCKET}/PMC1.2/PMC1.2.json"


# Which files an article needs


@pytest.mark.parametrize("href", ["fig1.jpg", "frai-09-1748985-g0001.jpg", "a_b.c-d", "fig1"])
def test_a_plain_file_name_is_accepted(href: str) -> None:
    assert graphic_name(href) == href


@pytest.mark.parametrize(
    "href",
    [
        "",
        "../secret",
        "a/../../b",
        "/etc/passwd",
        "a/b.jpg",
        "a\\b.jpg",
        "https://evil.example/x.jpg",
        "file:///etc/passwd",
        ".hidden",
        "a..b",
        "x" * 300,
    ],
)
def test_anything_else_never_becomes_a_path(href: str) -> None:
    assert graphic_name(href) is None


def test_refs_are_listed_once_and_bad_ones_apart() -> None:
    root = etree.fromstring(article("a.jpg", "a.jpg", "../b.jpg", "c.jpg"))

    refs = graphic_refs(root)

    assert refs.names == ("a.jpg", "c.jpg")
    assert refs.rejected == ("../b.jpg",)


@pytest.mark.parametrize(
    ("ids", "version"),
    [
        ('<article-id pub-id-type="pmcid-ver">PMC5.3</article-id>', "PMC5.3"),
        ('<article-id pub-id-type="pmcid">PMC5</article-id>', "PMC5.1"),
        ('<article-id pub-id-type="pmc">5</article-id>', "PMC5.1"),
        ('<article-id pub-id-type="doi">10.1/x</article-id>', None),
    ],
)
def test_pmc_version(ids: str, version: str | None) -> None:
    assert pmc_version(etree.fromstring(article(ids=ids))) == version


# The open-access record


def test_record_url() -> None:
    assert record_url("PMC1.2") == RECORD


def test_only_files_in_the_articles_own_folder_count() -> None:
    urls = [
        "s3://pmc-oa-opendata/PMC1.2/a.jpg?md5=aa",
        "s3://pmc-oa-opendata/PMC9.1/b.jpg?md5=bb",
        "s3://elsewhere/PMC1.2/c.jpg?md5=cc",
        "https://evil.example/PMC1.2/d.jpg?md5=dd",
        "s3://pmc-oa-opendata/PMC1.2/e.jpg",
    ]

    assert media_files({"media_urls": urls}, "PMC1.2") == {
        "a.jpg": MediaFile(f"{BUCKET}/PMC1.2/a.jpg", "aa")
    }


def test_a_record_with_no_media() -> None:
    assert media_files({}, "PMC1.2") == {}
    assert media_files({"media_urls": None}, "PMC1.2") == {}


def test_an_href_with_no_extension_finds_its_file() -> None:
    files = {"fig1.jpg": MediaFile("u", "m"), "fig2.jpg": MediaFile("v", "n")}

    assert find_media("fig1", files) == files["fig1.jpg"]
    assert find_media("fig1.jpg", files) == files["fig1.jpg"]
    assert find_media("fig3", files) is None


def test_an_ambiguous_href_finds_nothing() -> None:
    files = {"fig1.jpg": MediaFile("u", "m"), "fig1.tif": MediaFile("v", "n")}

    assert find_media("fig1", files) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (JPEG, True),
        (b"\x89PNG\r\n\x1a\nrest", True),
        (b"GIF89a", True),
        (b"II*\x00", True),
        (b"<html>Just a moment...</html>", False),
    ],
)
def test_is_image(body: bytes, expected: bool) -> None:
    assert is_image(body) is expected


# Downloading


def test_every_graphic_is_fetched() -> None:
    http, _ = serve(
        {RECORD: (200, record("a.jpg", "b.jpg")), f"{BUCKET}/PMC1.2/a.jpg": (200, JPEG)}
        | {f"{BUCKET}/PMC1.2/b.jpg": (200, JPEG)}
    )

    with http:
        graphics, lookup = fetch_graphics(article("a.jpg", "b.jpg"), http)

    assert graphics == {"a.jpg": JPEG, "b.jpg": JPEG}
    assert (lookup.status, lookup.reason) == ("ok", "2 of 2 fetched")


def test_a_paper_with_no_graphics_makes_no_requests() -> None:
    http, requested = serve({})

    with http:
        assert fetch_graphics(article(), http) == ({}, None)

    assert requested == []


def test_an_href_with_no_extension_is_stored_under_the_href() -> None:
    http, _ = serve({RECORD: (200, record("a.jpg")), f"{BUCKET}/PMC1.2/a.jpg": (200, JPEG)})

    with http:
        graphics, _ = fetch_graphics(article("a"), http)

    assert graphics == {"a": JPEG}


def test_a_failed_download_is_reported_and_the_rest_are_kept() -> None:
    http, _ = serve(
        {RECORD: (200, record("a.jpg", "b.jpg")), f"{BUCKET}/PMC1.2/a.jpg": (404, b"")}
        | {f"{BUCKET}/PMC1.2/b.jpg": (200, JPEG)}
    )

    with http:
        graphics, lookup = fetch_graphics(article("a.jpg", "b.jpg"), http)

    assert graphics == {"b.jpg": JPEG}
    assert lookup.status == "failed"
    assert lookup.reason.startswith("1 of 2 fetched: a.jpg:")


def test_a_corrupt_download_is_refused() -> None:
    http, _ = serve({RECORD: (200, record("a.jpg")), f"{BUCKET}/PMC1.2/a.jpg": (200, b"changed")})

    with http:
        graphics, lookup = fetch_graphics(article("a.jpg"), http)

    assert graphics == {}
    assert "MD5" in lookup.reason


def test_a_web_page_is_not_a_figure() -> None:
    page = b"<html>Just a moment...</html>"
    http, _ = serve(
        {RECORD: (200, record("a.jpg", body=page)), f"{BUCKET}/PMC1.2/a.jpg": (200, page)}
    )

    with http:
        graphics, lookup = fetch_graphics(article("a.jpg"), http)

    assert graphics == {}
    assert "isn't an image" in lookup.reason


def test_a_file_the_record_doesnt_list_is_reported() -> None:
    http, _ = serve({RECORD: (200, record())})

    with http:
        _, lookup = fetch_graphics(article("a.jpg"), http)

    assert "not in the article's open-access files" in lookup.reason


def test_no_record_is_reported() -> None:
    http, _ = serve({RECORD: (404, b"")})

    with http:
        graphics, lookup = fetch_graphics(article("a.jpg"), http)

    assert graphics == {}
    assert lookup.status == "failed"
    assert lookup.reason.startswith("0 of 1 fetched")


def test_an_article_outside_pmc_is_reported() -> None:
    http, requested = serve({})

    with http:
        _, lookup = fetch_graphics(article("a.jpg", ids=""), http)

    assert lookup.status == "failed"
    assert "no PMC id" in lookup.reason
    assert requested == []


def test_a_hostile_href_is_never_requested() -> None:
    http, requested = serve({RECORD: (200, record("a.jpg")), f"{BUCKET}/PMC1.2/a.jpg": (200, JPEG)})
    hostile = article("a.jpg", "https://evil.example/x.jpg", "../../secret")

    with http:
        graphics, lookup = fetch_graphics(hostile, http)

    assert graphics == {"a.jpg": JPEG}
    assert lookup.status == "failed"
    assert "1 of 3 fetched" in lookup.reason
    assert not any("evil" in url or "secret" in url for url in requested)


def test_a_hostile_pmc_id_never_reaches_a_url() -> None:
    http, requested = serve({})
    ids = '<article-id pub-id-type="pmcid-ver">../../../x</article-id>'

    with http:
        _, lookup = fetch_graphics(article("a.jpg", ids=ids), http)

    assert lookup.status == "failed"
    assert requested == []


def test_unreadable_xml_is_reported() -> None:
    http, _ = serve({})

    with http:
        _, lookup = fetch_graphics(b"<article><body>", http)

    assert lookup.status == "failed"


def test_many_failures_are_summarised() -> None:
    names = [f"f{n}.jpg" for n in range(8)]
    http, _ = serve({RECORD: (200, record())})

    with http:
        _, lookup = fetch_graphics(article(*names), http)

    assert lookup.reason.endswith("and 3 more")


# Resolving and the cache


def test_recorded_fixture_graphics_are_all_cached(replay, config: Config) -> None:
    transport = replay("fixture-doi")
    with client(transport, config.contact) as http:
        result = resolve(FIXTURE_DOI, config=config, http=http)

    assert transport.unused == []
    lookup = next(item for item in result.lookups if item.service == "PMC figures")
    assert (lookup.status, lookup.reason) == ("ok", "24 of 24 fetched")
    assert len(list((result.path.parent / "graphics").iterdir())) == 24


def test_recorded_graphics_survive_the_cache_offline(replay, config: Config) -> None:
    with client(Replay("fixture-doi"), config.contact) as http:
        first = resolve(FIXTURE_DOI, config=config, http=http)

    entry = cached_source(FIXTURE_DOI, cache_dir=config.cache_dir)

    assert entry.lookups == first.lookups
    assert entry.path == first.path


def stored(tmp_path: Path, graphics: dict[str, bytes] | None = None) -> Path:
    resolution = Resolution(input="x", attempts=(), tier="jats")
    cache.store(tmp_path, DOI, resolution, "source.xml", b"<article/>", graphics)
    return cache.entry_dir(tmp_path, DOI)


def test_the_cache_keeps_graphics_beside_the_source(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"a.jpg": JPEG})

    assert (entry / "graphics" / "a.jpg").read_bytes() == JPEG
    assert cache.load(tmp_path, DOI) is not None


def test_a_refresh_replaces_old_graphics(tmp_path: Path) -> None:
    stored(tmp_path, {"old.jpg": JPEG})

    entry = stored(tmp_path, {"new.jpg": JPEG})

    assert [path.name for path in (entry / "graphics").iterdir()] == ["new.jpg"]


def test_an_entry_with_no_graphics_has_no_directory(tmp_path: Path) -> None:
    assert not (stored(tmp_path) / "graphics").exists()


def test_a_changed_graphic_is_a_damaged_entry(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"a.jpg": JPEG})
    (entry / "graphics" / "a.jpg").write_bytes(b"changed")

    with pytest.raises(CacheError, match="--refresh"):
        cache.load(tmp_path, DOI)


def test_a_deleted_graphic_is_a_damaged_entry(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"a.jpg": JPEG})
    (entry / "graphics" / "a.jpg").unlink()

    with pytest.raises(CacheError, match="--refresh"):
        cache.load(tmp_path, DOI)


def test_a_manifest_naming_a_path_is_refused(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"a.jpg": JPEG})
    manifest = json.loads((entry / "manifest.json").read_text())
    manifest["graphics"] = {"../manifest.json": "0"}
    (entry / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(CacheError, match="bad graphic name"):
        cache.load(tmp_path, DOI)


def test_a_graphic_named_like_a_path_is_never_written(tmp_path: Path) -> None:
    with pytest.raises(CacheError, match="refusing"):
        stored(tmp_path, {"../escape.jpg": JPEG})

    assert not (tmp_path / "escape.jpg").exists()
