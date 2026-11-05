"""What a JATS article says it holds, read apart from the mapping to blocks, for the QA gate.

This walks the XML on its own. If it shared the mapper's walk it would miss what the mapper misses,
and `coverage.words` could never fail. So an element this module doesn't know counts as text.

An article has no pages, so `SourceEvidence.pages` is `None` and text is placed by section.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from offprint.adapters.jats.blocks import label_number, part_number
from offprint.adapters.jats.xml import (
    Element,
    JatsError,
    children,
    collapse,
    local,
    parse_article,
    text_of,
)
from offprint.extraction import SourceCaption, SourceEquation, SourceEvidence, SourceText

# Text the book doesn't show as text: images, maths, and labels the renderer writes itself.
_NOT_READ = frozenset(
    {
        "alt-text",
        "disp-formula",
        "graphic",
        "inline-formula",
        "inline-graphic",
        "label",
        "long-desc",
        "math",
        "media",
        "object-id",
        "pub-id",
        "tex-math",
    }
)
# Elements that end a word: without these, `<td>one</td><td>two</td>` would read as "onetwo".
_BOUNDARIES = frozenset(
    {
        "abstract",
        "ack",
        "app",
        "app-group",
        "article-title",
        "bio",
        "boxed-text",
        "caption",
        "code",
        "collab",
        "def",
        "def-item",
        "def-list",
        "disp-quote",
        "element-citation",
        "etal",
        "fig",
        "fig-group",
        "fn",
        "fn-group",
        "fpage",
        "given-names",
        "glossary",
        "kwd",
        "list",
        "list-item",
        "lpage",
        "mixed-citation",
        "name",
        "notes",
        "p",
        "preformat",
        "publisher-loc",
        "publisher-name",
        "ref",
        "ref-list",
        "sec",
        "source",
        "speech",
        "statement",
        "supplementary-material",
        "surname",
        "table",
        "table-wrap",
        "table-wrap-foot",
        "td",
        "term",
        "th",
        "title",
        "tr",
        "verse-group",
        "volume",
        "year",
    }
)
_SECTIONS = {
    "abstract": "Abstract",
    "ack": "Acknowledgments",
    "app": "Appendix",
    "notes": "Notes",
    "ref-list": "References",
    "sec": None,
}


@dataclass
class _TextReader:
    """Collects text, cutting it where the XML's structure ends a word."""

    texts: list[SourceText] = field(default_factory=list)
    _pending: list[str] = field(default_factory=list)

    def read(self, element: Element, section: str) -> None:
        self._pending.append(element.text or "")
        for child in children(element):
            name = local(child)
            if name not in _NOT_READ:
                ends_a_word = name in _BOUNDARIES
                if ends_a_word:
                    self.flush(section)
                self.read(child, _section_name(child, section))
                if ends_a_word:
                    self.flush(section)
            self._pending.append(child.tail or "")

    def flush(self, section: str) -> None:
        text = collapse("".join(self._pending))
        self._pending.clear()
        if text:
            self.texts.append(SourceText(text=text, section=section))


def _section_name(element: Element, current: str) -> str:
    name = local(element)
    if name not in _SECTIONS:
        return current
    return text_of(element.find("title")) or _SECTIONS[name] or current


def _regions(article: Element) -> Iterator[tuple[Element, str]]:
    """The parts of an article a reader gets, with the section their text starts in.

    Funding and conflict statements in `article-meta` are left out: they can repeat a section of
    `back`, and the mapper keeps only one of the two.
    """
    meta = article.find("front/article-meta")
    if meta is not None:
        for title in meta.iterfind("title-group/article-title"):
            yield title, "Title"
        for abstract in meta.iterfind("abstract"):
            yield abstract, "Abstract"
        for keywords in meta.iterfind("kwd-group"):
            yield keywords, "Keywords"
    yield from _float_regions(article)
    for extra in article.iter("sub-article", "response"):
        yield extra, f"<{local(extra)}>"


def _float_regions(article: Element) -> Iterator[tuple[Element, str]]:
    """The parts that hold the article's own figures, tables and equations."""
    for tag, section in (("body", "Body"), ("floats-group", "Floats"), ("back", "Back matter")):
        for region in article.iterfind(tag):
            yield region, section


def _number(element: Element, kind: str, counters: dict[str, int]) -> str:
    """Number a float as the IR does: from its label, or in order if it has none."""
    label = text_of(element.find("label"))
    if label:
        return label_number(label)
    counters[kind] = counters.get(kind, 0) + 1
    return f"U{counters[kind]}"


def _figure_captions(fig: Element, number: str) -> Iterator[SourceCaption]:
    """One per image, because the IR has one figure per image."""
    images = max(1, sum(1 for _ in fig.iter("graphic")))
    for index in range(1, images + 1):
        yield SourceCaption(kind="figure", number=part_number(number, index))


def _table_captions(wrap: Element, number: str) -> Iterator[SourceCaption]:
    tables = wrap.findall("table") or wrap.findall("alternatives/table")
    if tables:
        for index in range(1, len(tables) + 1):
            yield SourceCaption(kind="table", number=part_number(number, index))
    elif next(wrap.iter("graphic"), None) is not None:
        yield SourceCaption(kind="figure", number=f"Table {number}")
    else:
        yield SourceCaption(kind="table", number=number)


def _captions(regions: Iterable[Element]) -> Iterator[SourceCaption]:
    counters: dict[str, int] = {}
    for region in regions:
        for element in region.iter("fig", "table-wrap"):
            if local(element) == "fig":
                yield from _figure_captions(element, _number(element, "figure", counters))
            else:
                yield from _table_captions(element, _number(element, "table", counters))


def _equations(regions: Iterable[Element]) -> Iterator[SourceEquation]:
    for region in regions:
        for formula in region.iter("disp-formula"):
            if number := text_of(formula.find("label")).strip("()"):
                yield SourceEquation(number=number)


def collect_evidence(article: Element) -> SourceEvidence:
    """Read what `article` holds. Pure."""
    reader = _TextReader()
    for region, section in _regions(article):
        reader.read(region, section)
        reader.flush(section)
    floats = [region for region, _ in _float_regions(article)]
    return SourceEvidence(
        pages=None,
        texts=tuple(reader.texts),
        captions=tuple(_captions(floats)),
        equations=tuple(_equations(floats)),
    )


def read_evidence(path: Path) -> SourceEvidence:
    """Read what the QA gate compares the book with. It takes no part in the conversion."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise JatsError(f"can't read {path}: {error}") from error
    return collect_evidence(parse_article(data))
