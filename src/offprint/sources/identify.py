"""Work out what a user-supplied INPUT is. Pure: no filesystem, no network.

Because nothing looks at the disk, `10.1234/x.pdf` is a DOI even if a file has that name. Write
`./10.1234/x.pdf` to mean the file.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath
from urllib.parse import unquote, urlsplit

from offprint.ir import SourceTier
from offprint.sources.errors import InputError

_DOI = re.compile(r"10\.\d{4,9}/\S+")
_NEW_ARXIV_SHAPE = re.compile(r"(\d{4})\.(\d+)(?:v(\d+))?")
_OLD_ARXIV_SHAPE = re.compile(r"([a-z-]+)(?:\.[A-Za-z]{2})?/(\d{2})(\d{2})(\d{3})(?:v(\d+))?")
_URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SCHEMELESS_HOST = re.compile(r"(www\.)?(dx\.)?(doi|arxiv)\.org/", re.IGNORECASE)
_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org", "www.doi.org"})
_ARXIV_HOSTS = frozenset({"arxiv.org", "www.arxiv.org", "export.arxiv.org"})
_ARXIV_DOI_PREFIX = "10.48550/arxiv."

# Archives of the old arXiv scheme, which stopped accepting papers in March 2007.
_OLD_ARCHIVES = frozenset(
    {
        "acc-phys",
        "adap-org",
        "alg-geom",
        "ao-sci",
        "astro-ph",
        "atom-ph",
        "bayes-an",
        "chao-dyn",
        "chem-ph",
        "cmp-lg",
        "comp-gas",
        "cond-mat",
        "cs",
        "dg-ga",
        "funct-an",
        "gr-qc",
        "hep-ex",
        "hep-lat",
        "hep-ph",
        "hep-th",
        "math",
        "math-ph",
        "mtrl-th",
        "nlin",
        "nucl-ex",
        "nucl-th",
        "patt-sol",
        "physics",
        "plasm-ph",
        "q-alg",
        "q-bio",
        "quant-ph",
        "solv-int",
        "supr-con",
    }
)

_LOCAL_SUFFIXES: tuple[tuple[str, SourceTier], ...] = (
    (".pdf", "pdf"),
    (".xml", "jats"),
    (".tar.gz", "latex"),
)


@dataclass(frozen=True, slots=True)
class Doi:
    """A DOI, lowercased: DOIs are case-insensitive, so this is the canonical form."""

    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ArxivId:
    """An arXiv id without its version: `2401.01234` or `hep-th/9901001`."""

    base: str
    version: int | None = None

    def __str__(self) -> str:
        return self.base if self.version is None else f"{self.base}v{self.version}"


@dataclass(frozen=True, slots=True)
class LocalFile:
    path: PurePath
    tier: SourceTier

    def __str__(self) -> str:
        return str(self.path)


SourceInput = Doi | ArxivId | LocalFile


def detect_input(text: str) -> SourceInput:
    """Classify an INPUT, or raise `InputError` saying what's wrong with it."""
    value = text.strip()
    if not value:
        raise InputError("the input is empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InputError(f"{value!r} contains control characters")

    if _SCHEMELESS_HOST.match(value):
        value = f"https://{value}"
    if _URL_SCHEME.match(value):
        return _from_url(value)

    lowered = value.lower()
    if lowered.startswith("doi:"):
        return _doi(value[4:].strip())
    if lowered.startswith("arxiv:"):
        return _arxiv(value[6:].strip())

    if _DOI.fullmatch(value):
        return _doi(value)
    if _NEW_ARXIV_SHAPE.fullmatch(value) or _OLD_ARXIV_SHAPE.fullmatch(value):
        return _arxiv(value)

    for suffix, tier in _LOCAL_SUFFIXES:
        if lowered.endswith(suffix):
            return LocalFile(PurePath(value), tier)

    raise InputError(
        f"can't tell what {value!r} is: expected a DOI, an arXiv id, a doi.org or arxiv.org URL, "
        "or a .pdf, .xml or .tar.gz file"
    )


def _from_url(url: str) -> SourceInput:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError as error:
        raise InputError(f"{url!r} is not a valid URL: {error}") from None

    if parts.scheme.lower() in ("http", "https"):
        path = unquote(parts.path).strip("/")
        if host in _DOI_HOSTS:
            return _doi(path)
        if host in _ARXIV_HOSTS:
            return _arxiv_from_path(path, url)
    raise InputError(f"unsupported URL {url!r}: only doi.org and arxiv.org links are accepted")


def _arxiv_from_path(path: str, url: str) -> ArxivId:
    kind, _, rest = path.partition("/")
    if kind == "abs" and rest:
        return _arxiv(rest)
    if kind == "pdf" and rest:
        return _arxiv(rest.removesuffix(".pdf"))
    raise InputError(f"unsupported arXiv URL {url!r}: expected arxiv.org/abs/ID or /pdf/ID")


def _doi(value: str) -> Doi | ArxivId:
    if not _DOI.fullmatch(value):
        raise InputError(f"{value!r} is not a DOI: expected 10.NNNN/suffix")
    lowered = value.lower()
    # arXiv's own DOIs carry no extra information, and they aren't in Crossref.
    if lowered.startswith(_ARXIV_DOI_PREFIX):
        return _arxiv(lowered.removeprefix(_ARXIV_DOI_PREFIX))
    return Doi(lowered)


def _arxiv(value: str) -> ArxivId:
    if new := _NEW_ARXIV_SHAPE.fullmatch(value):
        return _new_arxiv(value, *new.groups())
    if old := _OLD_ARXIV_SHAPE.fullmatch(value):
        return _old_arxiv(value, *old.groups())
    raise InputError(f"{value!r} is not an arXiv id: expected 2401.01234 or hep-th/9901001")


def _new_arxiv(value: str, yymm: str, number: str, version: str | None) -> ArxivId:
    year, month = int(yymm[:2]), int(yymm[2:])
    if not 1 <= month <= 12:
        raise InputError(f"{value!r} is not an arXiv id: month {yymm[2:]} doesn't exist")
    if (year, month) < (7, 4):
        raise InputError(f"{value!r} is not an arXiv id: this scheme started in April 2007")
    digits = 4 if year < 15 else 5
    if len(number) != digits:
        raise InputError(f"{value!r} is not an arXiv id: {yymm} ids have {digits} digits")
    return ArxivId(f"{yymm}.{number}", _version(value, version))


def _old_arxiv(
    value: str, archive: str, yy: str, mm: str, number: str, version: str | None
) -> ArxivId:
    if archive not in _OLD_ARCHIVES:
        raise InputError(f"{value!r} is not an arXiv id: there is no archive {archive!r}")
    if not 1 <= int(mm) <= 12:
        raise InputError(f"{value!r} is not an arXiv id: month {mm} doesn't exist")
    if 8 <= int(yy) <= 90 or int(number) == 0:
        raise InputError(f"{value!r} is not an arXiv id: no paper has this number")
    # The subject class (`math.GT/...`) is not part of the id.
    return ArxivId(f"{archive}/{yy}{mm}{number}", _version(value, version))


def _version(value: str, version: str | None) -> int | None:
    if version is None:
        return None
    if int(version) == 0:
        raise InputError(f"{value!r} is not an arXiv id: versions start at v1")
    return int(version)
