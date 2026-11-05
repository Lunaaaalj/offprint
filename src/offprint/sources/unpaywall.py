"""Unpaywall: legal open-access locations for a DOI. Needs a real contact address."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from offprint.sources.errors import FetchError, InputError
from offprint.sources.http import Http
from offprint.sources.identify import ArxivId, Doi, detect_input

_API_URL = "https://api.unpaywall.org/v2/"


@dataclass(frozen=True, slots=True)
class OpenAccess:
    pdf_urls: tuple[str, ...] = ()
    arxiv_id: ArxivId | None = None


def lookup_url(doi: Doi, contact: str) -> str:
    return f"{_API_URL}{quote(doi.value, safe='')}?{urlencode({'email': contact})}"


def lookup(doi: Doi, contact: str, http: Http) -> OpenAccess:
    try:
        return parse_record(http.get_json(lookup_url(doi, contact)))
    except FetchError as error:
        if error.status == 422:
            message = "Unpaywall refused the contact address (HTTP 422): it wants your own email"
            raise FetchError(message, 422) from None
        raise


def parse_record(record: dict[str, Any]) -> OpenAccess:
    """Collect the PDF links, best location first, and any arXiv copy. Pure."""
    best = record.get("best_oa_location") or {}
    locations = [best, *(record.get("oa_locations") or [])]
    pdf_urls = dict.fromkeys(url for place in locations if (url := place.get("url_for_pdf")))
    arxiv_id = next(filter(None, map(_arxiv_from_location, locations)), None)
    return OpenAccess(pdf_urls=tuple(pdf_urls), arxiv_id=arxiv_id)


def _arxiv_from_location(location: dict[str, Any]) -> ArxivId | None:
    for key in ("url_for_landing_page", "url_for_pdf"):
        url = location.get(key)
        if url and "arxiv.org/" in url:
            try:
                parsed = detect_input(url)
            except InputError:
                continue
            if isinstance(parsed, ArxivId):
                return parsed
    return None
