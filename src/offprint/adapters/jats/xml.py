"""Reading untrusted XML: the only module that configures the parser.

Nothing here touches the network or the file system: no DTD is loaded and no entity is expanded.
"""

import re
from collections.abc import Iterator

from lxml import etree

XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
MATHML_MATH = "{http://www.w3.org/1998/Math/MathML}math"

type Element = etree._Element

_WHITESPACE = re.compile(r"[ \t\r\n]+")


class JatsError(ValueError):
    """The file can't be read as a JATS article."""


def parse_article(data: bytes) -> Element:
    """Return the `<article>` in `data`, bare or in PMC's `<pmc-articleset>` wrapper.

    Entities are refused rather than dropped: an unexpanded one would be a silent gap in the text,
    and an expanded one is how XML reads local files and fills the memory.
    """
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as error:
        raise JatsError(f"not well-formed XML: {error}") from None
    if next(root.iter(etree.Entity), None) is not None:
        raise JatsError("the XML uses entities, which offprint refuses to expand")
    article = _unwrap(root)
    if article.find("body") is None:
        raise JatsError("the article has no <body>, so there's no full text")
    return article


def _unwrap(root: Element) -> Element:
    name = local(root)
    if name == "article":
        return root
    if name != "pmc-articleset":
        raise JatsError(f"expected <article> or <pmc-articleset>, found <{name}>")
    articles = root.findall("article")
    if len(articles) != 1:
        raise JatsError(f"expected one article in the <pmc-articleset>, found {len(articles)}")
    return articles[0]


def local(element: Element) -> str:
    """The tag without its namespace."""
    return etree.QName(element).localname


def children(element: Element) -> Iterator[Element]:
    return element.iterchildren(etree.Element)


def collapse(text: str) -> str:
    """Collapse XML's insignificant whitespace, leaving no-break and thin spaces alone."""
    return _WHITESPACE.sub(" ", text).strip(" ")


def text_of(element: Element | None, *skip: str) -> str:
    """All the text in `element` on one line, leaving out the elements named in `skip`."""
    if element is None:
        return ""
    return collapse("".join(_text_parts(element, skip)))


def _text_parts(element: Element, skip: tuple[str, ...]) -> Iterator[str]:
    yield element.text or ""
    for child in children(element):
        if local(child) not in skip:
            yield from _text_parts(child, skip)
        yield child.tail or ""
