"""Crossref: bibliographic metadata for a DOI, and the links the publisher deposited with it."""

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from offprint.ir import Author, License, Meta, Text
from offprint.sources.errors import InputError
from offprint.sources.http import Http
from offprint.sources.identify import ArxivId, Doi, detect_input

_WORKS_URL = "https://api.crossref.org/works/"
_TAG = re.compile(r"<[^>]+>")
_CC_URL = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)/(\d\.\d)", re.I)
_XML_TYPES = frozenset({"application/xml", "text/xml", "application/jats+xml"})


@dataclass(frozen=True, slots=True)
class CrossrefWork:
    meta: Meta
    arxiv_id: ArxivId | None = None
    # A full-text XML link, kept only when the publisher declares an open licence.
    open_xml_url: str | None = None


def work_url(doi: Doi) -> str:
    return _WORKS_URL + quote(doi.value, safe="")


def lookup(doi: Doi, http: Http) -> CrossrefWork:
    return parse_work(http.get_json(work_url(doi)))


def parse_work(payload: dict[str, Any]) -> CrossrefWork:
    """Map a Crossref `/works/DOI` response. Pure."""
    work = payload["message"]
    license_ = _license(work.get("license", []))
    abstract = _plain(work.get("abstract", ""))
    meta = Meta(
        title=_plain(_first(work.get("title"))) or work["DOI"],
        authors=tuple(_author(person) for person in work.get("author", [])),
        journal=_plain(_first(work.get("container-title"))) or None,
        year=_year(work),
        volume=work.get("volume"),
        article_id=work.get("article-number") or work.get("page"),
        doi=work["DOI"].lower(),
        license=license_,
        abstract=(Text(abstract),) if abstract else (),
    )
    return CrossrefWork(
        meta=meta,
        arxiv_id=_preprint(work.get("relation", {})),
        open_xml_url=_xml_link(work.get("link", [])) if license_ else None,
    )


def spdx_from_url(url: str) -> str | None:
    """`https://creativecommons.org/licenses/by/4.0/` becomes `CC-BY-4.0`. Pure."""
    match = _CC_URL.search(url)
    if match is None:
        return None
    family, code, version = match.groups()
    if family.lower() == "publicdomain":
        return f"CC0-{version}" if code.lower() == "zero" else None
    return f"CC-{code.upper()}-{version}"


def _license(licenses: list[dict[str, Any]]) -> License | None:
    # The version of record's licence is the one that applies to what we'd fetch.
    ordered = sorted(licenses, key=lambda item: item.get("content-version") != "vor")
    for item in ordered:
        if spdx := spdx_from_url(item.get("URL", "")):
            return License(spdx=spdx)
    return None


def _preprint(relation: dict[str, Any]) -> ArxivId | None:
    for item in relation.get("has-preprint", []):
        try:
            parsed = detect_input(item.get("id", ""))
        except InputError:
            continue
        if isinstance(parsed, ArxivId):
            return parsed
    return None


def _xml_link(links: list[dict[str, Any]]) -> str | None:
    for link in links:
        url = link.get("URL", "")
        if (
            link.get("content-type") in _XML_TYPES
            and link.get("intended-application") != "similarity-checking"
            and urlsplit(url).scheme == "https"
        ):
            return url
    return None


def _author(person: dict[str, Any]) -> Author:
    name = " ".join(part for part in (person.get("given"), person.get("family")) if part)
    affiliations = person.get("affiliation") or [{}]
    return Author(name=name or person.get("name", ""), affiliation=affiliations[0].get("name"))


def _year(work: dict[str, Any]) -> int | None:
    for key in ("issued", "published", "created"):
        parts = (work.get(key) or {}).get("date-parts") or [[]]
        if parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _first(values: list[str] | None) -> str:
    return values[0] if values else ""


def _plain(markup: str) -> str:
    """Drop the JATS or HTML tags Crossref leaves in titles and abstracts."""
    return " ".join(html.unescape(_TAG.sub(" ", markup)).split())
