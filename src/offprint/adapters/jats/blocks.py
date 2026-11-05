"""`<body>` and `<back>` to IR blocks.

`BlockMapper` walks the tree. Graphics arrive through `load`, so the walk does no I/O.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from offprint.adapters.jats.citations import reference_doi, reference_runs
from offprint.adapters.jats.front import read_abstract
from offprint.adapters.jats.graphics import graphic_name
from offprint.adapters.jats.inline import (
    child_runs,
    collapse_label,
    inline_runs,
    read_formula,
    tidy_runs,
)
from offprint.adapters.jats.mathml import tex_text
from offprint.adapters.jats.tables import read_table
from offprint.adapters.jats.xml import XLINK_HREF, Element, children, local, text_of
from offprint.ir import (
    Asset,
    Block,
    Bold,
    Cell,
    Equation,
    Figure,
    Heading,
    ListItem,
    Paragraph,
    ParagraphRole,
    Problem,
    Provenance,
    Reference,
    Run,
    Runs,
    Table,
    Text,
)

ADAPTER = "jats"

_FLOATS = frozenset(
    {"fig", "fig-group", "table-wrap", "table-wrap-group", "disp-formula", "disp-formula-group"}
)
_CONTAINERS = frozenset(
    {
        "boxed-text",
        "disp-quote",
        "statement",
        "verse-group",
        "speech",
        "array",
        "glossary",
        "notes",
    }
)
# Block-level elements that can sit inside a paragraph, which then splits around them.
_BLOCK_IN_PARAGRAPH = (
    _FLOATS
    | _CONTAINERS
    | {
        "list",
        "def-list",
        "fn",
        "graphic",
        "supplementary-material",
        "preformat",
        "code",
        "sec",
    }
)
_ORDERED_LISTS = re.compile(r"order|alpha|roman|numer")
_FLOAT_LABEL = re.compile(r"^(?:fig(?:ure)?|tab(?:le)?)s?\.?\s+(.+?)$", re.IGNORECASE)
# Credits for the journal's editors, which belong with the article's other front matter.
_EDITORIAL_NOTES = frozenset({"edited-by", "reviewed-by"})
_CONFLICT_NOTES = frozenset({"conflict", "COI-statement", "coi-statement"})
_FUNDING_SECTION = re.compile(r"fund", re.IGNORECASE)

type LoadGraphic = Callable[[str], Asset | None]


def label_number(label: str) -> str:
    """The number in a float's `<label>`: `Figure 1.` gives `1`, `Fig. S2` gives `S2`.

    Other labels stay whole, so that `Scheme 1` can't collide with `Figure 1`.
    """
    label = label.strip().rstrip(".:")
    found = _FLOAT_LABEL.match(label)
    return found.group(1) if found else label


@dataclass
class BlockMapper:
    """Maps one article. Keeps the numbering, provenance and problems as it goes."""

    article: Element
    load: LoadGraphic
    blocks: list[Block] = field(default_factory=list)
    assets: dict[str, Asset] = field(default_factory=dict)
    provenance: dict[str, Provenance] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    missing: dict[str, None] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def run(self) -> None:
        self._front_paragraphs()
        body = self.article.find("body")
        self._section_content(body, level=1)
        for floats in self.article.findall("floats-group"):
            self._section_content(floats, level=1)
        self._back()
        for extra in self.article.iter("sub-article", "response"):
            self._problem("jats.unmapped_element", f"<{local(extra)}> wasn't converted")

    # Numbering and output

    def _next(self, prefix: str) -> int:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return self._counters[prefix]

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{self._next(prefix)}"

    def _add(self, block: Block, source: Element) -> None:
        self.blocks.append(block)
        path = source.getroottree().getpath(source)
        self.provenance[block.id] = Provenance(adapter=ADAPTER, note=path)

    def _problem(self, code: str, message: str, block_id: str | None = None) -> None:
        self.problems.append(Problem(code, message, block_id))

    def _paragraph(self, runs: Runs, source: Element, role: ParagraphRole = "body") -> None:
        if runs:
            self._add(Paragraph(id=self._next_id("p"), runs=runs, role=role), source)

    def _heading(self, runs: Runs, level: int, source: Element, number: str | None = None) -> None:
        self._add(Heading(id=self._next_id("h"), level=level, runs=runs, number=number), source)

    # Front and back matter

    def _front_paragraphs(self) -> None:
        meta = self.article.find("front/article-meta")
        if meta is None:
            return
        for runs in read_abstract(meta, self.problems):
            self._paragraph(runs, next(meta.iter("abstract")), "abstract")
        for note in self.article.iterfind("back/fn-group/fn"):
            if note.get("fn-type") in _EDITORIAL_NOTES:
                for paragraph in note.findall("p"):
                    self._paragraph(inline_runs(paragraph, self.problems), paragraph, "small")

    def _back(self) -> None:
        back = self.article.find("back")
        references = []
        if back is not None:
            for child in children(back):
                if local(child) == "ref-list":
                    references.append(child)
                else:
                    self._back_element(child)
        self._front_declarations(back)
        for ref_list in references:
            self._references(ref_list)

    def _back_element(self, element: Element) -> None:
        match local(element):
            case "sec" | "notes" | "app" | "glossary":
                self._section(element, level=1, default_title=_default_title(element))
            case "ack":
                self._section(element, level=1, default_title="Acknowledgments")
            case "fn-group":
                self._footnotes(element)
            case "app-group":
                self._appendices(element)
            case "bio":
                self._section(element, level=1, default_title="Biography")
            case _:
                self._unmapped(element)

    def _footnotes(self, group: Element) -> None:
        notes = [
            note for note in group.findall("fn") if note.get("fn-type") not in _EDITORIAL_NOTES
        ]
        if not notes:
            return
        title = group.find("title")
        runs = inline_runs(title, self.problems) if title is not None else (Text("Notes"),)
        self._heading(runs, 1, group)
        for note in notes:
            self._footnote(note)

    def _footnote(self, note: Element) -> None:
        label = text_of(note.find("label"))
        lead: Runs = (Text(f"{label} "),) if label else ()
        for child in children(note):
            if local(child) == "p":
                self._paragraph(tidy_runs((*lead, *inline_runs(child, self.problems))), child)
                lead = ()

    def _appendices(self, group: Element) -> None:
        title = group.find("title")
        level = 1
        if title is not None:
            self._heading(inline_runs(title, self.problems), 1, title)
            level = 2
        for child in children(group):
            if local(child) != "title":
                self._section(child, level=level, default_title=_default_title(child))

    def _front_declarations(self, back: Element | None) -> None:
        """Funding and conflict statements can sit in the front matter. They read as back matter."""
        meta = self.article.find("front/article-meta")
        if meta is None:
            return
        sections = [] if back is None else back.findall("sec")
        types = " ".join(section.get("sec-type", "") for section in sections)
        statement = next(meta.iter("funding-statement"), None)
        if statement is not None and not _FUNDING_SECTION.search(types):
            self._heading((Text("Funding"),), 1, statement)
            self._paragraph(inline_runs(statement, self.problems), statement)
        for note in meta.iterfind("author-notes/fn"):
            if note.get("fn-type") in _CONFLICT_NOTES:
                self._heading((Text("Conflict of interest"),), 1, note)
                self._footnote(note)

    def _references(self, ref_list: Element) -> None:
        title = ref_list.find("title")
        runs = inline_runs(title, self.problems) if title is not None else (Text("References"),)
        self._heading(runs, 1, ref_list)
        for ref in ref_list.iter("ref"):
            self._add(
                Reference(
                    id=self._next_id("ref"),
                    runs=reference_runs(ref, self.problems),
                    key=ref.get("id"),
                    doi=reference_doi(ref),
                ),
                ref,
            )

    # Sections

    def _section(self, section: Element, level: int, default_title: str | None = None) -> None:
        """A section with a heading. One with no title adds no level, so levels never jump."""
        title = section.find("title")
        label = collapse_label(section.find("label")) or None
        runs = inline_runs(title, self.problems) if title is not None else ()
        if not runs and default_title:
            runs = (Text(default_title),)
        if runs:
            self._heading(runs, level, title if title is not None else section, label)
            level += 1
        self._section_content(section, level)

    def _section_content(self, parent: Element, level: int) -> None:
        for child in children(parent):
            name = local(child)
            if name not in ("title", "label", "sec-meta"):
                self._block(child, level)

    def _block(self, element: Element, level: int, depth: int = 0) -> None:
        name = local(element)
        if name == "sec" or name == "app":
            self._section(element, level)
        elif name == "p":
            self._split_paragraph(element, level, depth)
        elif name in _FLOATS:
            self._float(element)
        elif name == "list":
            self._list(element, level, depth)
        elif name == "def-list":
            self._definitions(element)
        elif name == "fn":
            self._footnote(element)
        elif name == "graphic":
            self._figure_from(element, element, f"U{self._next('unlabelled')}", ())
        elif name == "supplementary-material":
            self._supplement(element)
        elif name in ("preformat", "code"):
            self._paragraph(inline_runs(element, self.problems), element)
        elif name in _CONTAINERS:
            self._container(element, level)
        else:
            self._unmapped(element)

    def _unmapped(self, element: Element) -> None:
        message = f"<{local(element)}> has no block mapping, so only its text was kept"
        self._problem("jats.unmapped_element", message)
        self._paragraph(inline_runs(element, self.problems), element)

    def _container(self, element: Element, level: int) -> None:
        for child in children(element):
            if local(child) in ("title", "label"):
                self._paragraph(_bold(inline_runs(child, self.problems)), child)
            elif local(child) == "attrib":
                self._paragraph(inline_runs(child, self.problems), child)
            else:
                self._block(child, level)

    def _segments(self, paragraph: Element) -> Iterator[Runs | Element]:
        """Split a paragraph at its block-level children, keeping the text on either side."""
        pending: list[Run] = [Text(paragraph.text)] if paragraph.text else []
        for child in children(paragraph):
            if local(child) in _BLOCK_IN_PARAGRAPH:
                yield tidy_runs(tuple(pending))
                yield child
                pending = []
            else:
                pending.extend(child_runs(child, self.problems))
            if child.tail:
                pending.append(Text(child.tail))
        yield tidy_runs(tuple(pending))

    def _split_paragraph(self, paragraph: Element, level: int, depth: int) -> None:
        for segment in self._segments(paragraph):
            if isinstance(segment, tuple):
                self._paragraph(segment, paragraph)
            else:
                self._block(segment, level, depth)

    # Lists

    def _list(self, element: Element, level: int, depth: int) -> None:
        ordered = _ORDERED_LISTS.search(element.get("list-type", "")) is not None
        for child in children(element):
            if local(child) == "list-item":
                self._list_item(child, ordered, level, depth)
            elif local(child) == "title":
                self._paragraph(_bold(inline_runs(child, self.problems)), child)

    def _list_item(self, item: Element, ordered: bool, level: int, depth: int) -> None:
        """One entry. Its paragraphs join, because the IR can't continue an item after a break."""
        label = text_of(item.find("label"))
        pending: list[Run] = [Text(f"{label} ")] if label else []

        def flush() -> None:
            runs = tidy_runs(tuple(pending))
            pending.clear()
            if runs:
                block = ListItem(id=self._next_id("li"), runs=runs, ordered=ordered, depth=depth)
                self._add(block, item)

        for child in children(item):
            if local(child) == "label":
                continue
            segments = self._segments(child) if local(child) == "p" else iter((child,))
            for segment in segments:
                if isinstance(segment, tuple):
                    pending.extend((Text(" "), *segment))
                else:
                    flush()
                    self._block(segment, level, depth + 1)
        flush()

    def _definitions(self, element: Element) -> None:
        for item in element.iter("def-item"):
            term, definition = item.find("term"), item.find("def")
            named = inline_runs(term, self.problems) if term is not None else ()
            described = inline_runs(definition, self.problems) if definition is not None else ()
            runs = tidy_runs((*_bold(named), Text(" "), *described))
            if runs:
                self._add(ListItem(id=self._next_id("li"), runs=runs), item)

    # Floats

    def _float(self, element: Element) -> None:
        match local(element):
            case "fig":
                self._figure(element)
            case "table-wrap":
                self._table_wrap(element)
            case "disp-formula":
                self._equation(element)
            case _:  # A group of floats, whose caption would otherwise be lost.
                caption = element.find("caption")
                if caption is not None:
                    self._paragraph(_caption(element, self.problems), caption)
                for child in children(element):
                    if local(child) in _FLOATS:
                        self._float(child)

    def _number(self, element: Element, kind: str) -> str:
        label = text_of(element.find("label"))
        return label_number(label) if label else f"U{self._next(f'unlabelled-{kind}')}"

    def _figure(self, fig: Element) -> None:
        number = self._number(fig, "figure")
        caption = _caption(fig, self.problems)
        graphics = list(fig.iter("graphic"))
        if not graphics:
            message = f"figure {number} has no <graphic>, so only its caption was kept"
            self._problem("jats.figure_without_graphic", message)
            self._paragraph(caption, fig)
        for index, graphic in enumerate(graphics, start=1):
            self._figure_from(graphic, fig, part_number(number, index), caption)

    def _figure_from(self, graphic: Element, source: Element, number: str, caption: Runs) -> None:
        asset = self._asset(graphic)
        if asset is not None:
            block = Figure(
                id=f"figure-{number}",
                number=number,
                asset=asset,
                caption=caption,
                alt=_alt(graphic),
            )
            self._add(block, source)

    def _asset(self, graphic: Element) -> str | None:
        """Load a graphic once. Missing ones are collected, to fail with the complete list."""
        href = graphic.get(XLINK_HREF, "")
        name = graphic_name(href)
        asset = self.load(name) if name else None
        if asset is None:
            self.missing[href] = None
            return None
        self.assets[asset.id] = asset
        return asset.id

    def _table_wrap(self, wrap: Element) -> None:
        number = self._number(wrap, "table")
        caption = _caption(wrap, self.problems)
        tables = wrap.findall("table") or wrap.findall("alternatives/table")
        if not tables:
            self._table_without_cells(wrap, number, caption)
        for index, table in enumerate(tables, start=1):
            part = part_number(number, index)
            header, rows = read_table(table, self.problems)
            block = Table(
                id=f"table-{part}",
                number=part,
                caption=caption,
                header=header,
                rows=tuple(tuple(row) for row in rows),
                notes=_table_notes(wrap, self.problems),
            )
            self._add(block, wrap)

    def _table_without_cells(self, wrap: Element, number: str, caption: Runs) -> None:
        """A table with no cells is an image if it has one (docs/ir.md), and text if it doesn't."""
        graphic = next(wrap.iter("graphic"), None)
        if graphic is not None:
            message = f"table {number} is an image in the source, so it's kept as a figure"
            self._problem("jats.table_as_figure", message)
            self._figure_from(graphic, wrap, f"Table {number}", caption)
            return
        self._unmapped(wrap)

    def _equation(self, formula: Element) -> None:
        block_id = self._next_id("equation")
        number = collapse_label(formula.find("label")) or None
        found = read_formula(formula, self.problems)
        latex = found.latex
        asset = None
        if latex is None:
            graphic = next(formula.iter("graphic"), None)
            if graphic is not None:
                asset = self._asset(graphic)
            elif found.text:
                message = f"equation {block_id!r} holds no maths markup, so it's shown as text"
                self._problem("jats.math_fallback", message, block_id)
                latex = tex_text(found.text)
            else:
                self._problem("jats.empty_formula", f"equation {block_id!r} is empty", block_id)
            if latex is None and asset is None:
                return
        block = Equation(id=block_id, alt=found.text, number=number, latex=latex, asset=asset)
        self._add(block, formula)

    def _supplement(self, element: Element) -> None:
        """The file itself isn't part of the book, but the text saying it exists is."""
        label = text_of(element.find("label"))
        runs = tidy_runs(
            (
                *_bold((Text(label),) if label else ()),
                Text(" "),
                *_caption(element, self.problems),
                *self._inner_paragraphs(element),
            )
        )
        self._paragraph(runs, element, "small")

    def _inner_paragraphs(self, element: Element) -> Runs:
        runs: list[Run] = []
        for child in element.findall("p"):
            runs.extend((Text(" "), *inline_runs(child, self.problems)))
        return tuple(runs)


def _default_title(element: Element) -> str | None:
    return text_of(element.find("label")) or None


def _bold(runs: Runs) -> Runs:
    return (Bold(runs),) if runs else ()


def part_number(number: str, index: int) -> str:
    """Number the second and later images or tables of one float, which the IR needs unique."""
    return number if index == 1 else f"{number}.{index}"


def _alt(graphic: Element) -> str | None:
    """The alt text, unless a machine wrote it.

    `machine-generated` alt text can't be trusted: in the Frontiers fixture, Figures 1 to 5 carry
    descriptions of another paper's diagrams. The caption, which the renderer falls back on, is
    the authors' own. No alt is better than one that confidently describes the wrong image.
    """
    alt = graphic.find("alt-text")
    if alt is None or alt.get("content-type") == "machine-generated":
        return None
    return text_of(alt) or None


def _caption(element: Element, problems: list[Problem]) -> Runs:
    """A float's caption, with any credit for it: dropping one could breach the license."""
    runs: list[Run] = []
    caption = element.find("caption")
    if caption is not None:
        runs.extend(inline_runs(caption, problems))
    for credit in (*element.findall("attrib"), *element.findall("permissions/copyright-statement")):
        runs.extend((Text(" "), *inline_runs(credit, problems)))
    return tidy_runs(tuple(runs))


def _table_notes(wrap: Element, problems: list[Problem]) -> Cell:
    runs: list[Run] = []
    for foot in wrap.findall("table-wrap-foot"):
        runs.extend((Text(" "), *inline_runs(foot, problems)))
    return tidy_runs(tuple(runs))
