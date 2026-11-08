"""`<front>` to `Meta`. Pure, apart from the list of problems."""

import re

from offprint.adapters.jats.inline import inline_runs, person_name
from offprint.adapters.jats.xml import XLINK_HREF, Element, children, local, text_of
from offprint.ir import Author, Bold, License, Meta, Problem, Run, Runs, Text

_ALI_LICENSE_REF = "{http://www.niso.org/schemas/ali/1.0/}license_ref"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_CC_LICENSE = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/(\d+\.\d+)", re.IGNORECASE)
_CC_ZERO = re.compile(r"creativecommons\.org/publicdomain/zero/(\d+\.\d+)", re.IGNORECASE)
_PUBLISHED = ("pub", "epub", "ppub", "nihms-submitted")
_YEAR = re.compile(r"\d{4}")


def read_meta(article: Element, problems: list[Problem]) -> Meta:
    meta = article.find("front/article-meta")
    if meta is None:
        problems.append(Problem("jats.no_front", "the article has no <article-meta>"))
        return Meta(title="", source_tier="jats")
    return Meta(
        title=_title(meta),
        authors=read_authors(meta),
        journal=text_of(article.find("front/journal-meta//journal-title")) or None,
        year=publication_year(meta),
        volume=text_of(meta.find("volume")) or None,
        article_id=text_of(meta.find("elocation-id")) or None,
        doi=_article_id(meta, "doi"),
        arxiv_id=_article_id(meta, "arxiv"),
        license=read_license(meta, problems),
        abstract=_flat(read_abstract(meta, problems)),
        keywords=read_keywords(meta, article.get(_XML_LANG)),
        source_tier="jats",
    )


def _title(meta: Element) -> str:
    title = text_of(meta.find("title-group/article-title"))
    subtitle = text_of(meta.find("title-group/subtitle"))
    return f"{title}: {subtitle}" if title and subtitle else title


def _article_id(meta: Element, kind: str) -> str | None:
    return text_of(meta.find(f"article-id[@pub-id-type='{kind}']")) or None


def read_authors(meta: Element) -> tuple[Author, ...]:
    """Every author, with the affiliations their `xref`s point to, or nested in the `contrib`."""
    affiliations = {aff.get("id"): _affiliation(aff) for aff in meta.iter("aff")}
    only = next(iter(affiliations.values())) if len(affiliations) == 1 else None
    authors = []
    for contrib in meta.iter("contrib"):
        if contrib.get("contrib-type") != "author":
            continue
        name = _contributor_name(contrib)
        if not name:
            continue
        found = [_affiliation(aff) for aff in contrib.findall("aff")]
        for xref in contrib.findall("xref[@ref-type='aff']"):
            found += [
                affiliations[key] for key in xref.get("rid", "").split() if key in affiliations
            ]
        corresponding = contrib.get("corresp") == "yes" or (
            contrib.find("xref[@ref-type='corresp']") is not None
        )
        own = tuple(dict.fromkeys(found)) or ((only,) if only else ())
        authors.append(Author(name=name, affiliations=own, corresponding=corresponding))
    return tuple(authors)


def _contributor_name(contrib: Element) -> str:
    name = next(contrib.iter("name"), None)
    if name is not None:
        return person_name(name)
    return text_of(contrib.find("collab")) or text_of(contrib.find("string-name"))


def _affiliation(aff: Element) -> str:
    """An `<aff>` on one line. Tagged parts with nothing between them get a comma."""
    parts = [aff.text or ""]
    for child in children(aff):
        if local(child) not in ("label", "sup", "email", "ext-link", "uri"):
            parts.append(text_of(child))
        tail = child.tail or ""
        parts.append(tail if tail.strip() else ", ")
    return _tidy_list("".join(parts))


def _tidy_list(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*,)+", ",", text)
    return text.strip(" ,;")


def publication_year(meta: Element) -> int | None:
    """The year of publication, preferring the article's own date to its collection's."""
    dates = meta.findall("pub-date")
    ranked = sorted(dates, key=lambda date: not _is_publication_date(date))
    for date in ranked:
        found = _YEAR.search(text_of(date.find("year")))
        if found:
            return int(found.group())
    return None


def _is_publication_date(date: Element) -> bool:
    return date.get("date-type", date.get("pub-type")) in _PUBLISHED


def read_license(meta: Element, problems: list[Problem]) -> License | None:
    """The license, as an SPDX id. A license we can't name is reported, not guessed."""
    permissions = meta.find("permissions")
    if permissions is None:
        return None
    holder = text_of(permissions.find("copyright-holder")) or None
    licenses = permissions.findall("license")
    urls = [url for license_ in licenses for url in _license_urls(license_)]
    spdx = next(filter(None, map(license_spdx, urls)), None)
    if spdx is None:
        if licenses:
            shown = ", ".join(urls) or "no URL"
            message = f"the article has a license offprint can't name ({shown})"
            problems.append(Problem("jats.license_unknown", message))
        return None
    return License(spdx=spdx, holder=holder)


def _license_urls(element: Element) -> list[str]:
    urls = [text_of(found) for found in element.iter(_ALI_LICENSE_REF)]
    urls += [element.get(XLINK_HREF, "")]
    urls += [found.get(XLINK_HREF, "") for found in element.iter("ext-link", "uri")]
    return [url for url in urls if url]


def license_spdx(url: str) -> str | None:
    """Map a Creative Commons URL to its SPDX id."""
    if found := _CC_LICENSE.search(url):
        return f"CC-{found.group(1).upper()}-{found.group(2)}"
    if found := _CC_ZERO.search(url):
        return f"CC0-{found.group(1)}"
    return None


def read_abstract(meta: Element, problems: list[Problem]) -> tuple[Runs, ...]:
    """The main abstract, one item per paragraph. Others are graphical or teasers."""
    abstracts = meta.findall("abstract")
    plain = next((item for item in abstracts if item.get("abstract-type") is None), None)
    abstract = plain if plain is not None else next(iter(abstracts), None)
    if abstract is None:
        return ()
    return tuple(_abstract_paragraphs(abstract, problems))


def _abstract_paragraphs(element: Element, problems: list[Problem]) -> list[Runs]:
    paragraphs: list[Runs] = []
    pending_title: Runs = ()
    for child in children(element):
        name = local(child)
        if name == "title" and element.tag == "sec":
            pending_title = inline_runs(child, problems)
        elif name == "sec":
            paragraphs += _abstract_paragraphs(child, problems)
        elif name == "p":
            runs = inline_runs(child, problems)
            if pending_title:
                runs = (Bold(pending_title), Text(" "), *runs)
                pending_title = ()
            if runs:
                paragraphs.append(runs)
    return paragraphs


def _flat(paragraphs: tuple[Runs, ...]) -> Runs:
    """Paragraphs as one run of text, which is what `Meta.abstract` holds."""
    runs: list[Run] = []
    for index, paragraph in enumerate(paragraphs):
        if index:
            runs.append(Text(" "))
        runs.extend(paragraph)
    return tuple(runs)


def read_keywords(meta: Element, language: str | None) -> tuple[str, ...]:
    """The keywords in the article's language, without repeats."""
    keywords: dict[str, None] = {}
    for group in meta.findall("kwd-group"):
        if group.get(_XML_LANG, language) == language:
            for keyword in group.iter("kwd"):
                if text := text_of(keyword):
                    keywords[text] = None
    return tuple(keywords)
