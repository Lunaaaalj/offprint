"""arXiv's licence, from OAI-PMH: the Atom API doesn't carry it (#60).

`test_recorded_*` replay real responses from `tests/recordings/`; the rest are pure or synthetic.
"""

from collections.abc import Callable

import httpx
import pytest
from replay_support import Replay, client

from offprint.ir import License, Meta
from offprint.sources import (
    ArxivId,
    Config,
    FetchError,
    Resolution,
    cache,
    detect_input,
    merge_meta,
    resolve,
)
from offprint.sources import arxiv as arxiv_api
from offprint.sources.licenses import spdx_from_url

ReplayFactory = Callable[[str], Replay]
CC_BY = License(spdx="CC-BY-4.0")
NEURIPS = ArxivId("2611.09197")


def _resolve(replay: ReplayFactory, scenario: str, text: str, config: Config) -> Resolution:
    transport = replay(scenario)
    with client(transport, config.contact) as http:
        result = resolve(text, config=config, http=http)
    assert transport.unused == []
    return result


def _lookup(resolution: Resolution, service: str):
    return next(item for item in resolution.lookups if item.service == service)


def _oai(license_element: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><metadata>
<arXiv xmlns="http://arxiv.org/OAI/arXiv/"><id>2401.01234</id>{license_element}</arXiv>
</metadata></record></GetRecord></OAI-PMH>""".encode()


# recorded


def test_recorded_atom_feed_has_no_license_but_oai_pmh_has(replay: ReplayFactory) -> None:
    with client(replay("arxiv-neurips-metadata")) as http:
        record = arxiv_api.lookup(NEURIPS, http)
        license_ = arxiv_api.lookup_license(NEURIPS, http)

    assert record.meta.arxiv_id == "2611.09197"
    assert record.meta.license is None
    assert license_ == CC_BY


def test_recorded_arxiv_paper_caches_its_license(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "arxiv-only", "2610.22829", config)

    assert result.meta is not None and result.meta.license == CC_BY
    assert _lookup(result, "arXiv OAI-PMH").status == "ok"
    cached = cache.load(config.cache_dir, ArxivId("2610.22829"))
    assert cached is not None and cached.meta is not None and cached.meta.license == CC_BY


def test_recorded_doi_with_a_preprint_asks_arxiv_too(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "doi-with-preprint", "10.1007/s00022-025-00782-5", config)

    assert result.meta is not None and result.meta.license == CC_BY
    assert _lookup(result, "arXiv OAI-PMH").status == "ok"


def test_recorded_missing_paper_asks_no_license(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "arxiv-missing", "2601.99999", config)

    assert all(item.service != "arXiv OAI-PMH" for item in result.lookups)


# synthetic


def test_synthetic_oai_outage_keeps_the_rest_of_the_record(config: Config) -> None:
    target = ArxivId("2401.01234")
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2401.01234v1</id><title>Synthetic</title></entry></feed>"""
    routes = {
        arxiv_api.query_url(target): httpx.Response(200, content=feed),
        arxiv_api.oai_url(target): httpx.Response(503),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    with client(httpx.MockTransport(handler)) as http:
        result = resolve("2401.01234", config=config, http=http)

    assert result.meta is not None and result.meta.title == "Synthetic"
    assert result.meta.license is None
    lookup = _lookup(result, "arXiv OAI-PMH")
    assert (lookup.status, lookup.reason) == ("failed", "oaipmh.arxiv.org answered HTTP 503")


# pure


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ("<license>http://creativecommons.org/licenses/by/4.0/</license>", CC_BY),
        (
            "<license>http://creativecommons.org/licenses/by-nc-sa/4.0/</license>",
            License(spdx="CC-BY-NC-SA-4.0"),
        ),
        (
            "<license>http://creativecommons.org/publicdomain/zero/1.0/</license>",
            License(spdx="CC0-1.0"),
        ),
        # arXiv's own licence lets arXiv distribute the paper, not us: no licence.
        ("<license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</license>", None),
        ("", None),
        ("<license> </license>", None),
    ],
)
def test_parse_oai_license(element: str, expected: License | None) -> None:
    assert arxiv_api.parse_oai_license(_oai(element)) == expected


def test_an_oai_error_has_no_license() -> None:
    body = b"""<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
        <error code="idDoesNotExist">no such record</error></OAI-PMH>"""

    assert arxiv_api.parse_oai_license(body) is None


def test_malformed_oai_xml_is_a_fetch_error() -> None:
    with pytest.raises(FetchError, match="malformed XML"):
        arxiv_api.parse_oai_license(b"<OAI-PMH")


def test_oai_url_uses_the_id_without_its_version() -> None:
    assert arxiv_api.oai_url(ArxivId("2611.09197", 2)) == (
        "https://oaipmh.arxiv.org/oai?verb=GetRecord"
        "&identifier=oai:arXiv.org:2611.09197&metadataPrefix=arXiv"
    )
    old_style = detect_input("hep-th/9901001")
    assert isinstance(old_style, ArxivId)
    assert "identifier=oai:arXiv.org:hep-th/9901001&" in arxiv_api.oai_url(old_style)


def test_merge_fills_the_license_from_arxiv_but_the_publishers_wins() -> None:
    published = Meta(title="P", doi="10.1/x")
    preprint = Meta(title="Q", arxiv_id="2401.01234", license=CC_BY)
    other = License(spdx="CC-BY-NC-4.0")

    assert merge_meta(published, preprint).license == CC_BY  # type: ignore[union-attr]
    merged = merge_meta(Meta(title="P", license=other), preprint)
    assert merged is not None and merged.license == other


def test_the_crossref_helper_is_the_shared_one() -> None:
    from offprint.sources import crossref

    assert crossref.spdx_from_url is spdx_from_url
    assert spdx_from_url("https://arxiv.org/licenses/nonexclusive-distrib/1.0/") is None
