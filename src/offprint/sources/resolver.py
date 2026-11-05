"""The resolver: find the best source for an input and put it in the cache.

This is the networked stage. `resolve` talks to the APIs, `cached_source` never does, and
`convert` only ever needs the second one (CLAUDE.md, rule 4).
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from offprint.ir import Meta, SourceTier
from offprint.sources import arxiv, cache, crossref, graphics, pmc, sniff, unpaywall
from offprint.sources.config import Config, load_config
from offprint.sources.errors import FetchError, InputError, NotResolvedError
from offprint.sources.http import Http
from offprint.sources.identify import ArxivId, Doi, LocalFile, detect_input
from offprint.sources.model import TIERS, Attempt, Lookup, Resolution

NO_CONTACT = (
    "Unpaywall needs a contact address. Set OFFPRINT_CONTACT_EMAIL, or contact_email "
    "in ~/.config/offprint/config.toml"
)
_ML_NOT_READY = "the ML fallback adapter isn't implemented yet"


class _Rejected(Exception):
    """A download arrived but isn't what the candidate promised."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    tier: SourceTier
    source: str
    url: str
    # Checks the bytes and returns the file name to cache them under, or raises `_Rejected`.
    accept: Callable[[bytes], str]


@dataclass(frozen=True, slots=True)
class _Fetched:
    tier: SourceTier
    filename: str
    body: bytes


def resolve(
    text: str,
    *,
    config: Config | None = None,
    http: Http | None = None,
    refresh: bool = False,
) -> Resolution:
    """Find the best source for `text` and cache it. Reuses the cache unless `refresh`."""
    target = detect_input(text)
    if isinstance(target, LocalFile):
        return _resolve_local(target)

    config = config or load_config()
    if not refresh and (cached := cache.load(config.cache_dir, target)):
        return cached

    if http is not None:
        return _resolve_remote(target, config, http)
    with Http(config.contact) as client:
        return _resolve_remote(target, config, client)


def cached_source(text: str, *, cache_dir: Path | None = None) -> Resolution:
    """Map an input to a local file without any network access.

    A local path is returned as it is. A DOI or arXiv id must already be in the cache, otherwise
    this raises `NotResolvedError`.
    """
    target = detect_input(text)
    if isinstance(target, LocalFile):
        return _resolve_local(target)
    root = cache_dir if cache_dir is not None else load_config().cache_dir
    entry = cache.load(root, target)
    if entry is None:
        raise NotResolvedError(f"{target} isn't in the cache: run `offprint resolve {target}`")
    return entry


def merge_meta(published: Meta | None, preprint: Meta | None) -> Meta | None:
    """Combine Crossref's and arXiv's records. Pure.

    Crossref describes the published paper, so it wins. arXiv fills what Crossref lacks, which
    is usually the abstract.
    """
    if published is None or preprint is None:
        return published or preprint
    return dataclasses.replace(
        published,
        arxiv_id=published.arxiv_id or preprint.arxiv_id,
        abstract=published.abstract or preprint.abstract,
        authors=published.authors or preprint.authors,
        year=published.year or preprint.year,
    )


def _resolve_local(target: LocalFile) -> Resolution:
    path = Path(target.path)
    if not path.is_file():
        raise NotResolvedError(f"no such file: {path}")
    attempts = [Attempt(target.tier, "local file", "chosen", "given as the input", str(path))]
    attempts += [
        Attempt(tier, "lookup", "skipped", "a local file was given, so nothing was looked up")
        for tier in TIERS
        if tier != target.tier
    ]
    return Resolution(input=str(path), attempts=tuple(attempts), path=path, tier=target.tier)


def _resolve_remote(target: Doi | ArxivId, config: Config, http: Http) -> Resolution:
    lookups: list[Lookup] = []

    def ask[T](service: str, call: Callable[[], T]) -> T | None:
        try:
            result = call()
        except FetchError as error:
            status = "missing" if error.status == 404 else "failed"
            lookups.append(Lookup(service, status, str(error)))
            return None
        lookups.append(Lookup(service, "ok", "answered"))
        return result

    doi = target if isinstance(target, Doi) else None
    arxiv_id = target if isinstance(target, ArxivId) else None
    work = open_access = record = pmc_record = None

    if arxiv_id is not None:
        record = ask("arXiv", lambda: arxiv.lookup(arxiv_id, http))
        doi = _doi_from(record.meta.doi) if record else None

    if doi is not None:
        work = ask("Crossref", lambda: crossref.lookup(doi, http))
        if config.contact:
            contact = config.contact
            open_access = ask("Unpaywall", lambda: unpaywall.lookup(doi, contact, http))
        else:
            lookups.append(Lookup("Unpaywall", "skipped", NO_CONTACT))
        if arxiv_id is None:
            arxiv_id = (work and work.arxiv_id) or (open_access and open_access.arxiv_id) or None
            if arxiv_id is not None:
                record = ask("arXiv", lambda: arxiv.lookup(arxiv_id, http))
            else:
                record = ask("arXiv", lambda: arxiv.find_by_doi(doi, http))
                arxiv_id = record.arxiv_id if record else None
        pmc_record = ask("Europe PMC", lambda: pmc.lookup(doi, http))

    if _outcome(lookups, "arXiv") == "missing":
        arxiv_id = None

    plan: list[_Candidate | Attempt] = [
        *_latex_tier(target, arxiv_id, lookups),
        *_jats_tier(doi, pmc_record, lookups, work, config),
        *_pdf_tier(doi, open_access, lookups, arxiv_id),
        Attempt("ml", "ML fallback", "unavailable", _ML_NOT_READY),
    ]
    attempts, fetched = _fetch_first(plan, http)

    meta = merge_meta(work.meta if work else None, record.meta if record else None)
    if fetched is None:
        return Resolution(str(target), tuple(attempts), tuple(lookups), meta)
    meta = dataclasses.replace(meta, source_tier=fetched.tier) if meta else None
    images: dict[str, bytes] = {}
    if fetched.tier == "jats":
        images, lookup = graphics.fetch_graphics(fetched.body, http)
        lookups += [lookup] if lookup else []
    resolution = Resolution(str(target), tuple(attempts), tuple(lookups), meta, tier=fetched.tier)
    return cache.store(config.cache_dir, target, resolution, fetched.filename, fetched.body, images)


def _doi_from(value: str | None) -> Doi | None:
    if not value:
        return None
    try:
        parsed = detect_input(f"doi:{value}")
    except InputError:
        return None
    return parsed if isinstance(parsed, Doi) else None


def _latex_tier(
    target: Doi | ArxivId, arxiv_id: ArxivId | None, lookups: list[Lookup]
) -> list[_Candidate | Attempt]:
    name = "arXiv e-print"
    if arxiv_id is not None:
        return [_Candidate("latex", name, arxiv.eprint_url(arxiv_id), _accept_eprint)]
    if _outcome(lookups, "arXiv") == "missing":
        return [Attempt("latex", name, "unavailable", f"arXiv has no paper {target}")]
    if failure := _failure(lookups, "arXiv"):
        return [Attempt("latex", name, "failed", failure)]
    return [Attempt("latex", name, "unavailable", "no arXiv preprint found for this DOI")]


def _jats_tier(
    doi: Doi | None,
    record: pmc.PmcRecord | None,
    lookups: list[Lookup],
    work: crossref.CrossrefWork | None,
    config: Config,
) -> list[_Candidate | Attempt]:
    pmc_name = "Europe PMC"
    if doi is None:
        return [Attempt("jats", pmc_name, "unavailable", "no DOI to search PubMed Central with")]

    plan: list[_Candidate | Attempt] = []
    if failure := _failure(lookups, pmc_name):
        plan.append(Attempt("jats", pmc_name, "failed", failure))
    elif record is None:
        plan.append(Attempt("jats", pmc_name, "unavailable", "this DOI isn't in PubMed Central"))
    elif not record.open_access:
        reason = f"{record.pmcid} isn't open access"
        plan.append(Attempt("jats", pmc_name, "unavailable", reason))
    else:
        url = pmc.europe_pmc_xml_url(record.pmcid)
        plan.append(_Candidate("jats", pmc_name, url, _accept_jats))
        url = pmc.efetch_url(record.pmcid, config.contact)
        plan.append(_Candidate("jats", "PubMed Central", url, _accept_jats))

    if work is not None and work.open_xml_url:
        plan.append(_Candidate("jats", "publisher XML", work.open_xml_url, _accept_jats))
    else:
        reason = "Crossref lists no openly licensed XML link"
        plan.append(Attempt("jats", "publisher XML", "unavailable", reason))
    return plan


def _pdf_tier(
    doi: Doi | None,
    open_access: unpaywall.OpenAccess | None,
    lookups: list[Lookup],
    arxiv_id: ArxivId | None,
) -> list[_Candidate | Attempt]:
    name = "Unpaywall"
    plan: list[_Candidate | Attempt] = []
    if doi is None:
        plan.append(Attempt("pdf", name, "unavailable", "no DOI to look up"))
    elif open_access is not None and open_access.pdf_urls:
        plan += [_Candidate("pdf", name, url, _accept_pdf) for url in open_access.pdf_urls]
    elif open_access is not None:
        plan.append(Attempt("pdf", name, "unavailable", "no open-access PDF known for this DOI"))
    elif failure := _failure(lookups, name):
        plan.append(Attempt("pdf", name, "failed", failure))
    else:
        plan.append(Attempt("pdf", name, "skipped", NO_CONTACT))
    if arxiv_id is not None:
        plan.append(_Candidate("pdf", "arXiv PDF", arxiv.pdf_url(arxiv_id), _accept_pdf))
    return plan


def _outcome(lookups: list[Lookup], service: str) -> str | None:
    return next((item.status for item in lookups if item.service == service), None)


def _failure(lookups: list[Lookup], service: str) -> str | None:
    found = (item for item in lookups if item.service == service and item.status != "ok")
    return next((item.reason for item in found if item.status != "skipped"), None)


def _fetch_first(
    plan: list[_Candidate | Attempt], http: Http
) -> tuple[list[Attempt], _Fetched | None]:
    """Walk the plan in tier order and download the first candidate that proves good."""
    attempts: list[Attempt] = []
    fetched: _Fetched | None = None
    for item in plan:
        if isinstance(item, Attempt):
            attempts.append(item)
        elif fetched is not None:
            reason = f"not needed: a {fetched.tier} source was chosen"
            attempts.append(Attempt(item.tier, item.source, "available", reason, item.url))
        else:
            try:
                body = http.get_bytes(item.url)
                fetched = _Fetched(item.tier, item.accept(body), body)
            except (FetchError, _Rejected) as error:
                attempts.append(Attempt(item.tier, item.source, "failed", str(error), item.url))
                continue
            reason = f"best source found, {len(body)} bytes downloaded"
            attempts.append(Attempt(item.tier, item.source, "chosen", reason, item.url))
    return attempts, fetched


def _accept_eprint(body: bytes) -> str:
    kind = sniff.classify_eprint(body)
    if kind == "pdf":
        raise _Rejected("arXiv has no TeX source for this paper, only a PDF")
    if kind == "unknown":
        raise _Rejected("the download is neither TeX source nor a PDF")
    return f"source.{kind}"


def _accept_jats(body: bytes) -> str:
    if not sniff.is_jats(body):
        raise _Rejected("the download isn't a JATS article with full text")
    return "source.xml"


def _accept_pdf(body: bytes) -> str:
    if not sniff.is_pdf(body):
        raise _Rejected("the download isn't a PDF")
    return "source.pdf"
