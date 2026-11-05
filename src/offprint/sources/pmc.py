"""PubMed Central, through Europe PMC's search and full-text services and NCBI's efetch."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from offprint.sources.http import Http
from offprint.sources.identify import Doi

_EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass(frozen=True, slots=True)
class PmcRecord:
    pmcid: str
    open_access: bool


def search_url(doi: Doi) -> str:
    query = quote(f'DOI:"{doi.value}"', safe="")
    return f"{_EUROPE_PMC}/search?query={query}&format=json&resultType=lite"


def europe_pmc_xml_url(pmcid: str) -> str:
    return f"{_EUROPE_PMC}/{quote(pmcid, safe='')}/fullTextXML"


def efetch_url(pmcid: str, contact: str | None) -> str:
    params = {"db": "pmc", "id": pmcid.removeprefix("PMC"), "rettype": "xml", "tool": "offprint"}
    if contact:
        params["email"] = contact
    return f"{_EFETCH}?{urlencode(params)}"


def lookup(doi: Doi, http: Http) -> PmcRecord | None:
    return parse_search(http.get_json(search_url(doi)), doi)


def parse_search(payload: dict[str, Any], doi: Doi) -> PmcRecord | None:
    """Find the record for exactly this DOI in a Europe PMC search response. Pure."""
    for result in payload.get("resultList", {}).get("result", []):
        pmcid = result.get("pmcid")
        if pmcid and result.get("doi", "").lower() == doi.value:
            return PmcRecord(pmcid=pmcid, open_access=result.get("isOpenAccess") == "Y")
    return None
