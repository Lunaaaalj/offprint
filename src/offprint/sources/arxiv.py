"""arXiv: metadata from the API, and the URLs of a paper's source and PDF."""

import re
from dataclasses import dataclass
from urllib.parse import quote
from xml.etree import ElementTree

from offprint.ir import Author, Meta, Text
from offprint.sources.errors import FetchError, InputError
from offprint.sources.http import Http
from offprint.sources.identify import ArxivId, Doi, detect_input

_API_URL = "https://export.arxiv.org/api/query?"
_MAX_DOI_MATCHES = 5
_NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_ENTRY_ID = re.compile(r"/abs/(.+?)(?:v\d+)?$")


@dataclass(frozen=True, slots=True)
class ArxivRecord:
    arxiv_id: ArxivId
    meta: Meta
    journal_ref: str | None = None


def query_url(arxiv_id: ArxivId) -> str:
    return f"{_API_URL}id_list={quote(str(arxiv_id), safe='/')}"


def eprint_url(arxiv_id: ArxivId) -> str:
    return f"https://arxiv.org/e-print/{arxiv_id}"


def pdf_url(arxiv_id: ArxivId) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def doi_search_url(doi: Doi) -> str:
    query = quote(f'doi:"{doi.value}"', safe="")
    return f"{_API_URL}search_query={query}&max_results={_MAX_DOI_MATCHES}"


def lookup(arxiv_id: ArxivId, http: Http) -> ArxivRecord:
    for record in parse_feed(http.get_bytes(query_url(arxiv_id))):
        if record.arxiv_id.base == arxiv_id.base:
            return record
    raise FetchError(f"arXiv has no paper {arxiv_id}", 404)


def find_by_doi(doi: Doi, http: Http) -> ArxivRecord | None:
    """Ask arXiv for a preprint of a published paper. Authors declare the DOI themselves."""
    for record in parse_feed(http.get_bytes(doi_search_url(doi))):
        if record.meta.doi == doi.value:
            return record
    return None


def parse_feed(feed: bytes) -> list[ArxivRecord]:
    """Map an Atom feed from the arXiv API. Pure."""
    try:
        root = ElementTree.fromstring(feed)
    except ElementTree.ParseError as error:
        raise FetchError(f"arXiv returned malformed XML: {error}") from None
    records = []
    for entry in root.findall("a:entry", _NS):
        match = _ENTRY_ID.search(_text(entry, "a:id"))
        parsed = _arxiv_id(match.group(1)) if match else None
        if parsed is None:
            continue
        summary = _text(entry, "a:summary")
        published = _text(entry, "a:published")
        meta = Meta(
            title=_text(entry, "a:title"),
            authors=tuple(_author(author) for author in entry.findall("a:author", _NS)),
            year=int(published[:4]) if published[:4].isdigit() else None,
            doi=_text(entry, "x:doi").lower() or None,
            arxiv_id=parsed.base,
            abstract=(Text(summary),) if summary else (),
        )
        records.append(ArxivRecord(parsed, meta, _text(entry, "x:journal_ref") or None))
    return records


def _arxiv_id(value: str) -> ArxivId | None:
    try:
        parsed = detect_input(f"arxiv:{value}")
    except InputError:
        return None
    return parsed if isinstance(parsed, ArxivId) else None


def _author(element: ElementTree.Element) -> Author:
    return Author(
        name=_text(element, "a:name"),
        affiliation=_text(element, "x:affiliation") or None,
    )


def _text(element: ElementTree.Element, path: str) -> str:
    found = element.find(path, _NS)
    return " ".join((found.text or "").split()) if found is not None else ""
