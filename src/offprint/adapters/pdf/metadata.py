"""Build `Meta` from the front matter, using the profile's patterns."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from offprint.cleanup import clean_text
from offprint.ir import Author, BBox, License, Meta, Runs
from offprint.profiles.schema import Profile


@dataclass(frozen=True, slots=True, kw_only=True)
class BylineBlock:
    """One block of the byline: the names it holds and the affiliation beside them.

    A block with no `names` is an affiliation on its own. It belongs to the names above it.
    """

    names: str
    affiliation: str
    bbox: BBox


@dataclass(frozen=True, slots=True, kw_only=True)
class FrontMatter:
    """The text the page layout gave us, before it's parsed."""

    title: str = ""
    byline: tuple[BylineBlock, ...] = ()
    keywords: str = ""
    citation: str = ""
    copyright: str = ""
    abstract: Runs = ()
    arxiv_id: str = ""
    venue: str = ""


@dataclass(slots=True)
class _Group:
    """The authors of one block of names, and the affiliations found for them."""

    bbox: BBox
    people: list[Author]
    affiliations: list[str]


def read_authors(byline: Sequence[BylineBlock], profile: Profile) -> tuple[Author, ...]:
    """Collect the authors of every block, each with the affiliations that belong to them.

    A block of names takes the affiliation written in the same block. An affiliation on its own
    belongs to the nearest block of names above it that it overlaps horizontally, as in a grid of
    authors. With none above, it goes to the authors left without one.
    """
    groups = [
        _Group(block.bbox, _people(block.names, profile), [block.affiliation])
        for block in byline
        if block.names
    ]
    orphans = []
    for block in byline:
        if block.names or not block.affiliation:
            continue
        owner = _owner(block.bbox, groups)
        if owner is None:
            orphans.append(block.affiliation)
        else:
            owner.affiliations.append(block.affiliation)
    authors = []
    for group in groups:
        own = [affiliation for affiliation in group.affiliations if affiliation]
        affiliations = tuple(dict.fromkeys(own or orphans))
        authors.extend(replace(person, affiliations=affiliations) for person in group.people)
    return tuple(authors)


def _owner(box: BBox, groups: Sequence[_Group]) -> _Group | None:
    """The group above `box`, overlapping it horizontally, with the least space between."""
    above = [
        group
        for group in groups
        if group.bbox[1] < box[1] and min(group.bbox[2], box[2]) > max(group.bbox[0], box[0])
    ]
    return min(above, key=lambda group: max(0, box[1] - group.bbox[3]), default=None)


def _people(text: str, profile: Profile) -> list[Author]:
    metadata = profile.metadata
    people = []
    marker = metadata.corresponding_marker
    separator = metadata.author_separator
    for raw in re.split(separator, text) if separator is not None else [text]:
        name = raw.replace(marker, "") if marker is not None else raw
        markers = tuple(char for char in name if char in metadata.author_markers)
        for char in metadata.author_markers:
            name = name.replace(char, "")
        if name.strip():
            people.append(
                Author(
                    name=name.strip(),
                    corresponding=marker is not None and marker in raw,
                    markers=markers,
                )
            )
    return people


def read_stamps(texts: Iterable[str], profile: Profile) -> tuple[str, str]:
    """Find the arXiv id and the venue line in the text blocks of the first page."""
    metadata = profile.metadata
    arxiv_id = venue = ""
    for text in texts:
        if metadata.arxiv_id is not None and not arxiv_id:
            found = re.search(metadata.arxiv_id, text)
            arxiv_id = found["arxiv_id"] if found else ""
        if metadata.venue is not None and not venue:
            found = re.search(metadata.venue, text)
            venue = found["venue"] if found else ""
    return arxiv_id, venue


def parse_keywords(text: str, profile: Profile) -> tuple[str, ...]:
    metadata = profile.metadata
    if metadata.keyword_prefix is None or metadata.keyword_separator is None:
        return ()
    body = re.sub(metadata.keyword_prefix, "", text)
    return tuple(word.strip() for word in re.split(metadata.keyword_separator, body) if word)


def parse_license(text: str, profile: Profile) -> License | None:
    pattern = profile.metadata.holder
    holder = re.search(pattern, text) if pattern is not None else None
    for rule in profile.metadata.licenses:
        if re.search(rule.pattern, text):
            return License(spdx=rule.spdx, holder=holder["holder"] if holder else None)
    return None


def build_meta(front: FrontMatter, pdf_metadata: dict[str, str], profile: Profile) -> Meta:
    metadata = profile.metadata
    citation = clean_text(front.citation or pdf_metadata.get("subject", ""))
    found = re.search(metadata.citation, citation.strip()) if metadata.citation else None
    fields = found.groupdict() if found else {}
    year = fields.get("year")
    return Meta(
        title=front.title or pdf_metadata.get("title", ""),
        authors=read_authors(front.byline, profile),
        journal=fields.get("journal") or front.venue or None,
        year=int(year) if year else None,
        volume=fields.get("volume"),
        article_id=fields.get("article_id"),
        doi=fields.get("doi"),
        arxiv_id=front.arxiv_id or None,
        license=parse_license(front.copyright, profile),
        abstract=front.abstract,
        keywords=parse_keywords(front.keywords, profile),
        source_tier="pdf",
    )
