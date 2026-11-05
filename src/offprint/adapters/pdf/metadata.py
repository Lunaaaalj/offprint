"""Build `Meta` from the front matter, using the profile's patterns."""

import re
from dataclasses import dataclass

from offprint.cleanup import clean_text
from offprint.ir import Author, License, Meta, Runs
from offprint.profiles.schema import Profile


@dataclass(frozen=True, slots=True, kw_only=True)
class FrontMatter:
    """The text the page layout gave us, before it's parsed."""

    title: str = ""
    authors: str = ""
    affiliation: str = ""
    keywords: str = ""
    citation: str = ""
    copyright: str = ""
    abstract: Runs = ()


def parse_authors(text: str, affiliation: str, profile: Profile) -> tuple[Author, ...]:
    metadata = profile.metadata
    authors = []
    for name in re.split(metadata.author_separator, text):
        clean = name.replace(metadata.corresponding_marker, "").strip()
        if clean:
            authors.append(
                Author(
                    name=clean,
                    affiliation=affiliation or None,
                    corresponding=metadata.corresponding_marker in name,
                )
            )
    return tuple(authors)


def parse_keywords(text: str, profile: Profile) -> tuple[str, ...]:
    metadata = profile.metadata
    body = re.sub(metadata.keyword_prefix, "", text)
    return tuple(word.strip() for word in re.split(metadata.keyword_separator, body) if word)


def parse_license(text: str, profile: Profile) -> License | None:
    holder = re.search(profile.metadata.holder, text)
    for rule in profile.metadata.licenses:
        if re.search(rule.pattern, text):
            return License(spdx=rule.spdx, holder=holder["holder"] if holder else None)
    return None


def build_meta(front: FrontMatter, pdf_metadata: dict[str, str], profile: Profile) -> Meta:
    metadata = profile.metadata
    citation = clean_text(front.citation or pdf_metadata.get("subject", ""))
    found = re.search(metadata.citation, citation.strip())
    fields = found.groupdict() if found else {}
    year = fields.get("year")
    return Meta(
        title=front.title or pdf_metadata.get("title", ""),
        authors=parse_authors(front.authors, front.affiliation, profile),
        journal=fields.get("journal"),
        year=int(year) if year else None,
        volume=fields.get("volume"),
        article_id=fields.get("article_id"),
        doi=fields.get("doi"),
        license=parse_license(front.copyright, profile),
        abstract=front.abstract,
        keywords=parse_keywords(front.keywords, profile),
        source_tier="pdf",
    )
