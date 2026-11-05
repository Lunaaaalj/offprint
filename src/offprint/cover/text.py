"""The words on a cover, derived from `Meta`. Pure functions, no layout."""

import re
from collections.abc import Sequence

from offprint.ir import Author, Meta

MAX_LISTED_AUTHORS = 4
DEFAULT_KICKER = "Article"

_ARTICLE_TYPES = (
    "review|survey|overview|meta-analysis|tutorial|primer|perspective|commentary|case study"
)
_TYPE_SUFFIX = re.compile(
    r"^(?P<title>.+?)\s*[:—–]\s*"
    rf"(?P<kicker>(?:an?\s+)?(?:[\w-]+\s+){{0,3}}(?:{_ARTICLE_TYPES}))\.?$",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    """Collapse the line breaks and runs of spaces that extraction leaves in metadata."""
    return " ".join(text.split())


def split_kicker(title: str) -> tuple[str, str | None]:
    """Split a trailing article type off a title: "Foo: a review" -> ("Foo", "a review").

    `Meta` has no article-type field, so the title's own suffix is the only signal the IR holds.
    """
    title = clean(title)
    match = _TYPE_SUFFIX.match(title)
    if match is None:
        return title, None
    return match["title"], match["kicker"]


def format_authors(authors: Sequence[Author]) -> str:
    """Join names as "A & B" or "A, B, C & D", or "A, B, … & Z" past `MAX_LISTED_AUTHORS`."""
    names = [clean(author.name) for author in authors]
    if len(names) > MAX_LISTED_AUTHORS:
        return f"{names[0]}, {names[1]}, … & {names[-1]}"
    if len(names) > 1:
        return f"{', '.join(names[:-1])} & {names[-1]}"
    return "".join(names)


def format_license(spdx: str) -> str:
    """Spell a license the way readers know it: "CC-BY-4.0" -> "CC BY 4.0"."""
    if spdx.upper().startswith("CC"):
        return spdx.replace("-", " ")
    return spdx


def format_citation(meta: Meta) -> str:
    """Build the footer's left: "Front. Artif. Intell. 9:1748985", or the best identifier held."""
    if meta.journal:
        locator = ":".join(part for part in (meta.volume, meta.article_id) if part)
        return clean(f"{meta.journal} {locator}")
    if meta.arxiv_id:
        return f"arXiv:{meta.arxiv_id}"
    if meta.doi:
        return f"doi:{meta.doi}"
    return ""


def format_imprint(meta: Meta) -> str:
    """Build the footer's right: "2026 · CC BY 4.0"."""
    year = str(meta.year) if meta.year else ""
    license_ = format_license(meta.license.spdx) if meta.license else ""
    return " · ".join(part for part in (year, license_) if part)
