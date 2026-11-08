"""The resolver end to end.

Tests named `test_recorded_*` replay real API responses from `tests/recordings/`. Tests named
`test_synthetic_*` use made-up responses, written inline, for paths the recordings can't reach:
Unpaywall refuses the placeholder contact, so no successful Unpaywall answer was ever recorded.
"""

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from replay_support import CONTACT, Replay, client

from offprint.ir import Author, Meta, Text
from offprint.sources import (
    ArxivId,
    CacheError,
    Config,
    Doi,
    NotResolvedError,
    Resolution,
    cached_source,
    crossref,
    detect_input,
    format_report,
    merge_meta,
    pmc,
    resolve,
    unpaywall,
)
from offprint.sources import arxiv as arxiv_api
from offprint.sources.resolver import NO_CONTACT

ARXIV_ONLY = "2610.22829"
PMC_DOI = "10.3389/fdmed.2025.1745526"
FIXTURE_DOI = "10.3389/frai.2026.1748985"
PREPRINT_DOI = "10.1007/s00022-025-00782-5"

ReplayFactory = Callable[[str], Replay]


def _resolve(replay: ReplayFactory, scenario: str, text: str, config: Config) -> Resolution:
    transport = replay(scenario)
    assert not transport.synthetic
    with client(transport, config.contact) as http:
        result = resolve(text, config=config, http=http)
    assert transport.unused == []  # the flow still matches what was recorded
    return result


def _attempt(resolution: Resolution, source: str):
    return next(item for item in resolution.attempts if item.source == source)


def _lookup(resolution: Resolution, service: str):
    return next(item for item in resolution.lookups if item.service == service)


# recorded: the three papers the issue names


def test_recorded_arxiv_only_paper_uses_latex(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "arxiv-only", ARXIV_ONLY, config)

    assert result.tier == "latex"
    assert result.path is not None and result.path.name == "source.tar.gz"
    assert result.path.is_relative_to(config.cache_dir)
    assert result.meta is not None
    assert result.meta.title == "KKM meets colorful Carathéodory"
    assert result.meta.arxiv_id == ARXIV_ONLY
    assert result.meta.source_tier == "latex"
    assert result.meta.doi is None
    assert _attempt(result, "arXiv e-print").status == "chosen"
    assert _attempt(result, "Europe PMC").reason == "no DOI to search PubMed Central with"
    assert _attempt(result, "arXiv PDF").status == "available"


def test_recorded_pmc_paper_uses_jats(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "pmc-jats", PMC_DOI, config)

    assert result.tier == "jats"
    assert result.path is not None and result.path.name == "source.xml"
    assert result.path.read_bytes().count(b"<body") >= 1
    assert result.meta is not None
    assert result.meta.doi == PMC_DOI
    assert result.meta.journal == "Frontiers in Dental Medicine"
    assert result.meta.license is not None and result.meta.license.spdx == "CC-BY-4.0"
    assert result.meta.source_tier == "jats"
    assert _attempt(result, "arXiv e-print").reason == "no arXiv preprint found for this DOI"
    assert _attempt(result, "Europe PMC").status == "chosen"
    assert _attempt(result, "PubMed Central").status == "available"


def test_recorded_fixture_doi_falls_back_from_a_500(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "fixture-doi", FIXTURE_DOI, config)

    assert result.tier == "jats"
    assert result.meta is not None
    assert result.meta.title.startswith("Artificial intelligence techniques for classification")
    assert [author.name for author in result.meta.authors] == ["Y. Nibila", "M. Sivagami"]
    assert result.meta.year == 2026
    assert result.meta.volume == "9"
    assert result.meta.article_id == "1748985"
    assert result.meta.license is not None and result.meta.license.spdx == "CC-BY-4.0"

    europe = _attempt(result, "Europe PMC")
    assert (europe.status, europe.reason) == ("failed", "www.ebi.ac.uk answered HTTP 500")
    assert _attempt(result, "PubMed Central").status == "chosen"


def test_recorded_doi_finds_its_arxiv_preprint(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "doi-with-preprint", PREPRINT_DOI, config)

    assert result.tier == "latex"
    assert result.meta is not None
    assert result.meta.doi == PREPRINT_DOI
    assert result.meta.arxiv_id == "2509.10460"
    assert result.meta.journal is not None  # published metadata wins over the preprint's


def test_recorded_unpaywall_refuses_the_placeholder(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "fixture-doi", FIXTURE_DOI, config)

    lookup = _lookup(result, "Unpaywall")
    assert lookup.status == "failed"
    assert "refused the contact address" in lookup.reason
    assert _attempt(result, "Unpaywall").status == "failed"


def test_recorded_missing_arxiv_paper(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "arxiv-missing", "2601.99999", config)

    assert result.path is None and result.tier is None
    assert _lookup(result, "arXiv").status == "missing"
    assert _attempt(result, "arXiv e-print").reason == "arXiv has no paper 2601.99999"
    assert not any(item.source == "arXiv PDF" for item in result.attempts)
    assert "choice: none" in format_report(result)


def test_recorded_missing_doi(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "doi-missing", "10.3389/frai.2026.0000000", config)

    assert result.path is None
    assert result.meta is None
    assert _lookup(result, "Crossref").status == "missing"
    assert _attempt(result, "Europe PMC").reason == "this DOI isn't in PubMed Central"


def test_a_failed_resolution_is_not_cached(replay: ReplayFactory, config: Config) -> None:
    _resolve(replay, "arxiv-missing", "2601.99999", config)

    with pytest.raises(NotResolvedError):
        cached_source("2601.99999", cache_dir=config.cache_dir)


# no contact address


def test_recorded_no_contact_skips_unpaywall_with_a_reason(
    replay: ReplayFactory, tmp_path: Path
) -> None:
    transport = replay("fixture-doi")
    anonymous = Config(cache_dir=tmp_path / "anonymous")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "unpaywall" not in str(request.url)
        for exchange in transport.unused:
            # With no contact, efetch is called without the recorded `email` parameter.
            if exchange["url"].split("&email=")[0] == str(request.url):
                body = (transport.directory / exchange["body"]).read_bytes()
                return httpx.Response(exchange["status"], content=body)
        raise AssertionError(f"no recording for {request.url}")

    with client(httpx.MockTransport(handler), None) as http:
        result = resolve(FIXTURE_DOI, config=anonymous, http=http)

    assert _lookup(result, "Unpaywall").reason == NO_CONTACT
    assert _attempt(result, "Unpaywall").status == "skipped"
    assert "OFFPRINT_CONTACT_EMAIL" in format_report(result)


# the cache: resolution is separate from conversion


def test_recorded_rerun_comes_from_the_cache(replay: ReplayFactory, config: Config) -> None:
    first = _resolve(replay, "pmc-jats", PMC_DOI, config)

    offline = replay("pmc-jats")
    with client(offline) as http:
        second = resolve(PMC_DOI, config=config, http=http)

    assert offline.requests == []
    assert second.from_cache and not first.from_cache
    assert (second.path, second.tier, second.meta) == (first.path, first.tier, first.meta)
    assert second.attempts == first.attempts
    assert second.lookups == first.lookups


def test_recorded_refresh_looks_everything_up_again(replay: ReplayFactory, config: Config) -> None:
    _resolve(replay, "pmc-jats", PMC_DOI, config)

    transport = replay("pmc-jats")
    with client(transport) as http:
        result = resolve(PMC_DOI, config=config, http=http, refresh=True)

    assert transport.unused == []
    assert not result.from_cache


@pytest.mark.parametrize(
    "spelling",
    [PMC_DOI, PMC_DOI.upper(), f"doi:{PMC_DOI}", f"https://doi.org/{PMC_DOI}"],
)
def test_recorded_cached_source_needs_no_network(
    replay: ReplayFactory, config: Config, spelling: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved = _resolve(replay, "pmc-jats", PMC_DOI, config)

    def no_client(*_: object, **__: object) -> None:
        raise AssertionError("cached_source must not build an HTTP client")

    monkeypatch.setattr("offprint.sources.resolver.Http", no_client)
    entry = cached_source(spelling, cache_dir=config.cache_dir)

    assert entry.path == resolved.path
    assert entry.tier == "jats"
    assert entry.meta == resolved.meta


def test_recorded_cached_source_uses_the_configured_cache(
    replay: ReplayFactory, config: Config
) -> None:
    # `config.cache_dir` is the directory OFFPRINT_CACHE_DIR points at in these tests.
    _resolve(replay, "arxiv-only", ARXIV_ONLY, config)

    entry = cached_source(f"https://arxiv.org/abs/{ARXIV_ONLY}")

    assert entry.tier == "latex"


def test_an_unresolved_input_is_an_error_not_a_download(config: Config) -> None:
    with pytest.raises(NotResolvedError, match="offprint resolve 10.1000/xyz"):
        cached_source("10.1000/xyz", cache_dir=config.cache_dir)


def test_local_files_are_used_as_they_are(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7")

    for result in (resolve(str(path)), cached_source(str(path))):
        assert (result.path, result.tier) == (path, "pdf")
        assert result.lookups == ()
        assert _attempt(result, "local file").status == "chosen"

    report = format_report(resolve(str(path)))
    assert "a local file was given, so nothing was looked up" in report


def test_a_missing_local_file_is_an_error(tmp_path: Path) -> None:
    for function in (resolve, cached_source):
        with pytest.raises(NotResolvedError, match="no such file"):
            function(str(tmp_path / "missing.pdf"))


def test_a_damaged_cache_file_is_reported(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "pmc-jats", PMC_DOI, config)
    assert result.path is not None
    result.path.write_bytes(b"truncated")

    with pytest.raises(CacheError, match="doesn't match its checksum"):
        cached_source(PMC_DOI, cache_dir=config.cache_dir)


@pytest.mark.parametrize(
    "tamper",
    [
        {"file": "../../../etc/passwd"},
        {"file": "/etc/passwd"},
        {"manifest_version": 99},
        {"attempts": "nonsense"},
    ],
)
def test_a_tampered_manifest_is_refused(
    replay: ReplayFactory, config: Config, tamper: dict[str, object]
) -> None:
    result = _resolve(replay, "pmc-jats", PMC_DOI, config)
    assert result.path is not None
    manifest = result.path.parent / "manifest.json"
    manifest.write_text(
        json.dumps({**json.loads(manifest.read_text(encoding="utf-8")), **tamper}),
        encoding="utf-8",
    )

    with pytest.raises(CacheError, match="damaged"):
        cached_source(PMC_DOI, cache_dir=config.cache_dir)


def test_a_manifest_that_is_not_json_is_refused(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "pmc-jats", PMC_DOI, config)
    assert result.path is not None
    (result.path.parent / "manifest.json").write_text("{", encoding="utf-8")

    with pytest.raises(CacheError, match="damaged"):
        cached_source(PMC_DOI, cache_dir=config.cache_dir)


# the report


def test_recorded_report_explains_every_tier(replay: ReplayFactory, config: Config) -> None:
    result = _resolve(replay, "fixture-doi", FIXTURE_DOI, config)

    report = format_report(result)

    for expected in (
        f"input: {FIXTURE_DOI}",
        "tier 1 (latex):",
        "arXiv e-print: unavailable: no arXiv preprint found for this DOI",
        "tier 2 (jats):",
        "Europe PMC: failed: www.ebi.ac.uk answered HTTP 500",
        "PubMed Central: chosen: best source found",
        "publisher XML: unavailable: Crossref lists no openly licensed XML link",
        "tier 3 (pdf):",
        "Unpaywall: failed: Unpaywall refused the contact address",
        "tier 4 (ml):",
        "ML fallback: unavailable",
        "choice: tier 2 (jats)",
        "source.xml",
    ):
        assert expected in report


# synthetic: paths no recording reaches

SYNTHETIC_PDF = b"%PDF-1.7 synthetic"
SYNTHETIC_DOI = "10.5555/synthetic"


def _synthetic_routes(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _synthetic_crossref() -> dict[str, object]:
    return {"message": {"DOI": SYNTHETIC_DOI, "title": ["A synthetic paper"]}}


def _empty_feed() -> bytes:
    return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def test_synthetic_unpaywall_pdf_is_the_last_resort(config: Config) -> None:
    doi = Doi(SYNTHETIC_DOI)
    transport = _synthetic_routes(
        {
            crossref.work_url(doi): httpx.Response(200, json=_synthetic_crossref()),
            unpaywall.lookup_url(doi, CONTACT): httpx.Response(
                200,
                json={"best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf"}},
            ),
            arxiv_api.doi_search_url(doi): httpx.Response(200, content=_empty_feed()),
            pmc.search_url(doi): httpx.Response(200, json={"resultList": {"result": []}}),
            "https://repo.example.org/a.pdf": httpx.Response(200, content=SYNTHETIC_PDF),
        }
    )
    with client(transport) as http:
        result = resolve(SYNTHETIC_DOI, config=config, http=http)

    assert result.tier == "pdf"
    assert result.path is not None and result.path.read_bytes() == SYNTHETIC_PDF
    assert result.meta is not None and result.meta.source_tier == "pdf"


def test_synthetic_login_page_instead_of_a_pdf_is_rejected(config: Config) -> None:
    doi = Doi(SYNTHETIC_DOI)
    transport = _synthetic_routes(
        {
            crossref.work_url(doi): httpx.Response(200, json=_synthetic_crossref()),
            unpaywall.lookup_url(doi, CONTACT): httpx.Response(
                200,
                json={"best_oa_location": {"url_for_pdf": "https://repo.example.org/a.pdf"}},
            ),
            arxiv_api.doi_search_url(doi): httpx.Response(200, content=_empty_feed()),
            pmc.search_url(doi): httpx.Response(200, json={"resultList": {"result": []}}),
            "https://repo.example.org/a.pdf": httpx.Response(200, content=b"<html>log in</html>"),
        }
    )
    with client(transport) as http:
        result = resolve(SYNTHETIC_DOI, config=config, http=http)

    assert result.path is None
    assert _attempt(result, "Unpaywall").reason == "the download isn't a PDF"


def test_synthetic_arxiv_without_tex_falls_back_to_its_pdf(config: Config) -> None:
    target = ArxivId("2401.01234")
    transport = _synthetic_routes(
        {
            arxiv_api.query_url(target): httpx.Response(
                200,
                content=b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
                <id>http://arxiv.org/abs/2401.01234v1</id><title>Synthetic</title></entry></feed>""",
            ),
            arxiv_api.eprint_url(target): httpx.Response(200, content=SYNTHETIC_PDF),
            arxiv_api.pdf_url(target): httpx.Response(200, content=SYNTHETIC_PDF),
        }
    )
    with client(transport) as http:
        result = resolve("2401.01234", config=config, http=http)

    assert result.tier == "pdf"
    eprint = _attempt(result, "arXiv e-print")
    assert (eprint.status, eprint.reason) == (
        "failed",
        "arXiv has no TeX source for this paper, only a PDF",
    )
    assert "a better tier failed" in format_report(result)


def test_synthetic_arxiv_id_with_a_doi_gets_published_metadata(config: Config) -> None:
    target = ArxivId("2401.01234")
    doi = Doi(SYNTHETIC_DOI)
    feed = f"""<feed xmlns="http://www.w3.org/2005/Atom"
                     xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
      <id>http://arxiv.org/abs/2401.01234v1</id><title>Preprint title</title>
      <summary>Preprint abstract.</summary><arxiv:doi>{SYNTHETIC_DOI}</arxiv:doi>
    </entry></feed>"""
    transport = _synthetic_routes(
        {
            arxiv_api.query_url(target): httpx.Response(200, content=feed.encode()),
            crossref.work_url(doi): httpx.Response(200, json=_synthetic_crossref()),
            unpaywall.lookup_url(doi, CONTACT): httpx.Response(200, json={}),
            pmc.search_url(doi): httpx.Response(200, json={"resultList": {"result": []}}),
            arxiv_api.eprint_url(target): httpx.Response(
                200, content=gzip.compress(rb"\documentclass{article}")
            ),
        }
    )
    with client(transport) as http:
        result = resolve("2401.01234", config=config, http=http)

    assert result.path is not None and result.path.name == "source.tex.gz"
    assert result.meta is not None
    assert result.meta.title == "A synthetic paper"
    assert result.meta.abstract == (Text("Preprint abstract."),)
    assert (result.meta.doi, result.meta.arxiv_id) == (SYNTHETIC_DOI, "2401.01234")


def test_synthetic_arxiv_api_outage_still_tries_the_eprint(config: Config) -> None:
    target = ArxivId("2401.01234")
    transport = _synthetic_routes(
        {
            arxiv_api.query_url(target): httpx.Response(503),
            arxiv_api.eprint_url(target): httpx.Response(200, content=b"not a known format"),
            arxiv_api.pdf_url(target): httpx.Response(503),
        }
    )
    with client(transport) as http:
        result = resolve("2401.01234", config=config, http=http)

    assert result.path is None
    assert _lookup(result, "arXiv").reason == "export.arxiv.org answered HTTP 503"
    assert _attempt(result, "arXiv PDF").reason == "arxiv.org answered HTTP 503"


# pure parsers


def test_merge_prefers_crossref_and_fills_from_arxiv() -> None:
    published = Meta(title="Published", journal="J", doi="10.1/x")
    preprint = Meta(
        title="Preprint",
        arxiv_id="2401.01234",
        abstract=(Text("From arXiv"),),
        authors=(Author(name="A"),),
        year=2024,
    )

    merged = merge_meta(published, preprint)

    assert merged == Meta(
        title="Published",
        journal="J",
        doi="10.1/x",
        arxiv_id="2401.01234",
        abstract=(Text("From arXiv"),),
        authors=(Author(name="A"),),
        year=2024,
    )
    assert merge_meta(None, preprint) == preprint
    assert merge_meta(published, None) == published
    assert merge_meta(None, None) is None


@pytest.mark.parametrize(
    ("url", "spdx"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("http://creativecommons.org/licenses/by-nc-nd/3.0/igo", "CC-BY-NC-ND-3.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("https://www.elsevier.com/tdm/userlicense/1.0/", None),
    ],
)
def test_spdx_from_url(url: str, spdx: str | None) -> None:
    assert crossref.spdx_from_url(url) == spdx


def test_crossref_strips_markup_and_finds_a_preprint_link() -> None:
    work = crossref.parse_work(
        {
            "message": {
                "DOI": "10.5555/X",
                "title": ["A <i>synthetic</i> title &amp; more"],
                "abstract": "<jats:title>Abstract</jats:title><jats:p>Some text.</jats:p>",
                "author": [{"name": "A Consortium", "sequence": "first", "affiliation": []}],
                "relation": {
                    "has-preprint": [
                        {"id": "10.1101/biorxiv", "id-type": "doi"},
                        {"id": "10.48550/arXiv.2401.01234", "id-type": "doi"},
                    ]
                },
            }
        }
    )

    assert work.meta.title == "A synthetic title & more"
    assert work.meta.abstract == (Text("Abstract Some text."),)
    assert work.meta.authors == (Author(name="A Consortium"),)
    assert work.meta.doi == "10.5555/x"
    assert work.arxiv_id == ArxivId("2401.01234")


def _work_with_link(license_url: str, link: dict[str, str]) -> crossref.CrossrefWork:
    return crossref.parse_work(
        {
            "message": {
                "DOI": "10.5555/x",
                "license": [{"URL": license_url, "content-version": "vor"}],
                "link": [link],
            }
        }
    )


def test_a_publisher_xml_link_needs_an_open_licence() -> None:
    link = {"URL": "https://pub.example.org/a.xml", "content-type": "application/xml"}

    open_work = _work_with_link("https://creativecommons.org/licenses/by/4.0/", link)
    closed_work = _work_with_link("https://pub.example.org/tdm-licence", link)

    assert open_work.open_xml_url == "https://pub.example.org/a.xml"
    assert closed_work.open_xml_url is None


def test_a_similarity_checking_link_is_not_a_full_text_source() -> None:
    link = {
        "URL": "https://pub.example.org/a.xml",
        "content-type": "application/xml",
        "intended-application": "similarity-checking",
    }

    work = _work_with_link("https://creativecommons.org/licenses/by/4.0/", link)

    assert work.open_xml_url is None


def test_unpaywall_lists_pdfs_once_and_finds_an_arxiv_copy() -> None:
    record = unpaywall.parse_record(
        {
            "best_oa_location": {"url_for_pdf": "https://a.example/x.pdf"},
            "oa_locations": [
                {"url_for_pdf": "https://a.example/x.pdf"},
                {
                    "url_for_pdf": "https://arxiv.org/pdf/2401.01234",
                    "url_for_landing_page": "https://arxiv.org/abs/2401.01234",
                },
            ],
        }
    )

    assert record.pdf_urls == ("https://a.example/x.pdf", "https://arxiv.org/pdf/2401.01234")
    assert record.arxiv_id == ArxivId("2401.01234")


def test_unpaywall_handles_a_closed_paper() -> None:
    assert unpaywall.parse_record({"best_oa_location": None, "oa_locations": []}) == (
        unpaywall.OpenAccess()
    )


def test_pmc_search_requires_the_exact_doi() -> None:
    doi = Doi("10.5555/x")
    payload = {
        "resultList": {
            "result": [
                {"doi": "10.5555/other", "pmcid": "PMC1", "isOpenAccess": "Y"},
                {"doi": "10.5555/X", "pmcid": "PMC2", "isOpenAccess": "N"},
            ]
        }
    }

    assert pmc.parse_search(payload, doi) == pmc.PmcRecord("PMC2", open_access=False)
    assert pmc.parse_search({"resultList": {"result": []}}, doi) is None


def test_arxiv_feed_with_old_style_ids() -> None:
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"
                     xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
      <id>http://arxiv.org/abs/hep-th/9901001v3</id>
      <title>  Wrapped
        title </title>
      <published>1999-01-04T00:00:00Z</published>
      <author><name>A. Author</name><arxiv:affiliation>Somewhere</arxiv:affiliation></author>
      <arxiv:doi>10.1016/S0370-2693(99)00001-1</arxiv:doi>
    </entry></feed>"""

    [record] = arxiv_api.parse_feed(feed)

    assert record.arxiv_id == detect_input("hep-th/9901001")
    assert record.meta.title == "Wrapped title"
    assert record.meta.year == 1999
    assert record.meta.doi == "10.1016/s0370-2693(99)00001-1"
    assert record.meta.authors == (Author(name="A. Author", affiliations=("Somewhere",)),)
