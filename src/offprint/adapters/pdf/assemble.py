"""Turn extracted pages into an IR document: find each element, order them, emit blocks."""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from offprint.adapters.pdf.equations import (
    DisplayEquation,
    EquationPiece,
    group_equations,
    is_display_equation,
)
from offprint.adapters.pdf.extract import PageData
from offprint.adapters.pdf.figures import figure_region, include_labels
from offprint.adapters.pdf.layout import Column, column_of, reading_order
from offprint.adapters.pdf.metadata import FrontMatter, build_meta
from offprint.adapters.pdf.roles import block_role, block_text, first_span
from offprint.adapters.pdf.tables import (
    clean_table,
    drop_detections_in_figures,
    table_options,
    trim_detections,
)
from offprint.cleanup import (
    CaptionOptions,
    ParagraphOptions,
    ScriptOptions,
    TextOptions,
    cell_lines,
    clean_text,
    drop_prefix,
    join_continued_tables,
    join_paragraphs,
    keep_hyphen_from_vocabulary,
    merge_touching_blocks,
    pair_captions,
    plain_text,
    script_positions,
    separate_words,
    spans_to_runs,
    square_rows,
    vocabulary,
)
from offprint.cleanup.geometry import contains, touches, union
from offprint.cleanup.text import KeepHyphen, excerpt
from offprint.extraction import ExtractedTable, Span, TableCell, TextBlock
from offprint.ir import (
    Asset,
    BBox,
    Block,
    Cell,
    Document,
    Equation,
    Figure,
    Heading,
    ListItem,
    Paragraph,
    ParagraphRole,
    Problem,
    Provenance,
    Reference,
    Runs,
    Table,
)
from offprint.profiles.schema import Profile, Role

ADAPTER = "pdf"

type Crop = Callable[..., Asset]
"""Renders part of a page: `crop(page=, bbox=, zoom=, grayscale=, asset_id=)`."""


class LayoutError(ValueError):
    """The page layout broke an assumption the output depends on."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Placed:
    column: Column
    top: float
    bottom: float
    page: int
    bbox: BBox


@dataclass(frozen=True, slots=True, kw_only=True)
class TextElement(_Placed):
    role: Role
    block: TextBlock


@dataclass(frozen=True, slots=True, kw_only=True)
class MetaElement(_Placed):
    """A sidebar block kept as front matter. It reads after the rest of its page."""

    block: TextBlock


@dataclass(frozen=True, slots=True, kw_only=True)
class FigureElement(_Placed):
    number: str
    caption: Runs
    crop_box: BBox
    alt: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TableElement(_Placed):
    table: ExtractedTable
    number: str | None
    caption: Runs
    continued: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EquationElement(_Placed):
    equation: DisplayEquation


type Element = TextElement | MetaElement | FigureElement | TableElement | EquationElement


@dataclass(frozen=True, slots=True, kw_only=True)
class _Caption:
    block: TextBlock
    kind: str
    number: str
    text: str
    runs: Runs


def find_scripts(spans: Sequence[Span], profile: Profile) -> tuple[Span, ...]:
    """A line's spans, with the sub- and superscripts the profile asks for found from geometry."""
    rules = profile.text.scripts
    if rules is None:
        return tuple(spans)
    return script_positions(spans, ScriptOptions(size_ratio=rules.size_ratio, offset=rules.offset))


def _words(spans: Sequence[Span], profile: Profile) -> tuple[Span, ...]:
    return separate_words(find_scripts(spans, profile), profile.text.word_gap)


def _block_runs(block: TextBlock, profile: Profile, keep_hyphen: KeepHyphen | None) -> Runs:
    lines = (_words(line.spans, profile) for line in block.lines)
    return spans_to_runs(list(lines), TextOptions(keep_hyphen=keep_hyphen))


def merge_caption_fragments(blocks: Sequence[TextBlock], profile: Profile) -> list[TextBlock]:
    """Merge the caption-styled blocks of a page that touch, leaving other blocks alone."""
    options = CaptionOptions(
        touch_gap=profile.captions.touch_gap, line_tolerance=profile.captions.line_tolerance
    )
    pieces = [b for b in blocks if block_role(b, profile, "caption") == "caption"]
    others = [b for b in blocks if block_role(b, profile, "caption") != "caption"]
    return [*others, *merge_touching_blocks(pieces, options)]


def read_caption(
    block: TextBlock, profile: Profile, keep_hyphen: KeepHyphen | None = None
) -> _Caption | None:
    """Parse a block as a figure or table caption, ignoring spans not in a caption font."""
    captions = profile.captions
    fonts = tuple(captions.fonts)
    kept = [
        tuple(span for span in line.spans if span.font.startswith(fonts)) for line in block.lines
    ]
    text = clean_text(" ".join("".join(s.text for s in line) for line in kept if line)).strip()
    for kind, pattern in (("figure", captions.figure), ("table", captions.table)):
        found = re.match(pattern, text)
        if found is not None:
            lines = [_words(line, profile) for line in kept if line]
            runs = spans_to_runs(lines, TextOptions(keep_hyphen=keep_hyphen))
            label = len(plain_text(runs)) - len(found["text"])
            return _Caption(
                block=block,
                kind=kind,
                number=found["number"],
                text=found["text"],
                runs=drop_prefix(runs, label),
            )
    return None


def _bounding_boxes(
    blocks: Sequence[TextBlock],
    captions: Sequence[_Caption],
    tables: Sequence[ExtractedTable],
    profile: Profile,
) -> list[BBox]:
    """Return the blocks that can bound a figure from above: running text, not tables or labels."""
    caption_blocks = {id(caption.block) for caption in captions}
    layout = profile.page
    boxes = []
    for block in blocks:
        span = first_span(block)
        if (
            span is not None
            and id(block) not in caption_blocks
            and span.font.startswith(tuple(profile.figures.bounding_fonts))
            and block.bbox[1] > layout.header_y
            and block.bbox[3] < layout.footer_y
            and not any(touches(block.bbox, table.bbox) for table in tables)
        ):
            boxes.append(block.bbox)
    return boxes


def _number_order(caption: _Caption) -> tuple[int, str]:
    return (len(caption.number), caption.number)


def _figures(
    page: PageData,
    blocks: Sequence[TextBlock],
    captions: Sequence[_Caption],
    bounds: Sequence[BBox],
    profile: Profile,
) -> list[FigureElement]:
    figures = sorted((c for c in captions if c.kind == "figure"), key=_number_order)
    caption_blocks = {id(caption.block) for caption in captions}
    texts = [
        (block.bbox, len(block_text(block).split()))
        for block in blocks
        if id(block) not in caption_blocks
    ]
    alts: Sequence[str | None] = page.figure_alts
    if len(alts) != len(figures):
        alts = [None] * len(figures)
    elements = []
    for caption, alt in zip(figures, alts, strict=True):
        others = [c.block.bbox for c in captions if c is not caption]
        region = figure_region(
            caption.block.bbox,
            blocks=bounds,
            captions=others,
            graphics=page.graphics,
            page_width=page.width,
            profile=profile,
        )
        crop_box = region.bbox
        if profile.figures.labels is not None:
            crop_box = include_labels(crop_box, texts, profile.figures.labels)
        elements.append(
            FigureElement(
                column=region.column,
                top=crop_box[1],
                bottom=caption.block.bbox[3],
                page=page.number,
                bbox=union((crop_box, caption.block.bbox)),
                number=caption.number,
                caption=caption.runs,
                crop_box=crop_box,
                alt=alt,
            )
        )
    return elements


def _tables(
    page: PageData,
    tables: Sequence[ExtractedTable],
    captions: Sequence[_Caption],
    spans: Sequence[Span],
    profile: Profile,
) -> list[TableElement]:
    labels = [c for c in captions if c.kind == "table"]
    pairs = pair_captions(
        [c.block.bbox for c in labels],
        [t.bbox for t in tables],
        side=profile.captions.table_side,
        y_tolerance=profile.tables.caption_tolerance,
    )
    paired = {index: label for index, label in zip(pairs, labels, strict=True) if index is not None}
    for label, index in zip(labels, pairs, strict=True):
        is_new = re.search(profile.captions.continuation, label.text) is None
        if index is None and is_new:
            raise LayoutError(f"page {page.number}: no table found for caption {label.number}")

    elements = []
    for index, detected in enumerate(tables):
        label = paired.get(index)
        table = clean_table(detected, spans, profile)
        continued = label is None or (
            re.search(profile.captions.continuation, label.text) is not None
        )
        top = table.bbox[1] if label is None else min(table.bbox[1], label.block.bbox[1])
        elements.append(
            TableElement(
                column=column_of(table.bbox, profile.page),
                top=top,
                bottom=table.bbox[3],
                page=page.number,
                bbox=table.bbox,
                table=table,
                number=None if label is None else label.number,
                caption=() if label is None else label.runs,
                continued=continued,
            )
        )
    return elements


def _dropped(page: PageData, block: TextBlock) -> Problem:
    text = excerpt(block_text(block))
    return Problem(
        code="pdf.dropped_text",
        message=f"page {page.number}: text touching a figure or table is left out: {text!r}",
        page=page.number,
        bbox=block.bbox,
    )


def _text_elements(
    page: PageData,
    blocks: Sequence[TextBlock],
    captions: Sequence[_Caption],
    occupied: Sequence[BBox],
    profile: Profile,
    problems: list[Problem],
) -> tuple[list[Element], list[EquationPiece]]:
    layout = profile.page
    caption_blocks = {id(caption.block) for caption in captions}
    elements: list[Element] = []
    pieces: list[EquationPiece] = []
    for block in blocks:
        box = block.bbox
        if id(block) in caption_blocks or first_span(block) is None:
            continue
        if box[3] < layout.header_y or box[1] > layout.footer_y:
            continue
        touched = [other for other in occupied if touches(box, other)]
        if touched:
            if not any(contains(other, box, profile.figures.edge_tolerance) for other in touched):
                problems.append(_dropped(page, block))
            continue
        sidebar = layout.sidebar
        if sidebar is not None and page.number == sidebar.page and box[2] < sidebar.x_max:
            if re.match(sidebar.keep, block_text(block)):
                elements.append(
                    MetaElement(
                        column="full",
                        top=page.height + box[1],
                        bottom=page.height + box[3],
                        page=page.number,
                        bbox=box,
                        block=block,
                    )
                )
            continue
        role = block_role(block, profile)
        if role is None or role == "ignore":
            continue
        column = column_of(box, layout)
        if role in ("body", "small") and is_display_equation(block, column, profile):
            pieces.append(EquationPiece(block=block, column=column))
            continue
        elements.append(
            TextElement(
                column=column,
                top=box[1],
                bottom=box[3],
                page=page.number,
                bbox=box,
                role=role,
                block=block,
            )
        )
    return elements, pieces


def page_elements(
    page: PageData,
    profile: Profile,
    keep_hyphen: KeepHyphen | None = None,
    problems: list[Problem] | None = None,
) -> list[Element]:
    """Find everything on a page and return it in reading order.

    What the adapter can't place is added to `problems`, when the caller passes a list.
    """
    problems = problems if problems is not None else []
    blocks = merge_caption_fragments(page.blocks, profile)
    parsed = (read_caption(block, profile, keep_hyphen) for block in blocks)
    captions = [caption for caption in parsed if caption is not None]
    tables = trim_detections(page.tables, blocks, profile)

    bounds = _bounding_boxes(blocks, captions, tables, profile)
    figures = _figures(page, blocks, captions, bounds, profile)
    tables = drop_detections_in_figures(tables, [f.crop_box for f in figures], profile)
    spans = [
        span for block in blocks for line in block.lines for span in line.spans if span.text.strip()
    ]
    table_elements = _tables(page, tables, captions, spans, profile)

    occupied = [t.bbox for t in tables] + [f.crop_box for f in figures]
    texts, pieces = _text_elements(page, blocks, captions, occupied, profile, problems)
    equations = [
        EquationElement(
            column=equation.column,
            top=equation.bbox[1],
            bottom=equation.bbox[3],
            page=page.number,
            bbox=equation.bbox,
            equation=equation,
        )
        for equation in group_equations(pieces, profile)
    ]
    return reading_order([*figures, *table_elements, *texts, *equations])


def join_tables(elements: Sequence[Element], profile: Profile) -> list[Element]:
    """Join table pieces in reading order, keeping each joined table at its first piece."""
    pieces = [e for e in elements if isinstance(e, TableElement)]
    if pieces and pieces[0].continued:
        raise LayoutError(f"page {pieces[0].page}: a table with no caption and nothing to continue")
    joined = join_continued_tables(
        [piece.table for piece in pieces],
        [piece.continued for piece in pieces],
        table_options(profile),
    )
    firsts = [piece for piece in pieces if not piece.continued]
    tables = {id(first): square_rows(t) for first, t in zip(firsts, joined, strict=True)}
    result: list[Element] = []
    for element in elements:
        if not isinstance(element, TableElement):
            result.append(element)
        elif id(element) in tables:
            result.append(replace(element, table=tables[id(element)]))
    return result


class _Emitter:
    """Builds blocks with unique ids and their provenance."""

    def __init__(self, profile: Profile, keep_hyphen: KeepHyphen | None, crop: Crop) -> None:
        self.profile = profile
        self.keep_hyphen = keep_hyphen
        self.crop = crop
        self.blocks: list[Block] = []
        self.assets: dict[str, Asset] = {}
        self.provenance: dict[str, Provenance] = {}
        self.front: dict[str, str] = {}
        self.abstract: Runs = ()
        self.counter = 0

    def _add(self, block: Block, element: Element) -> None:
        self.blocks.append(block)
        self.provenance[block.id] = Provenance(
            adapter=ADAPTER, page=element.page, bbox=element.bbox
        )

    def _next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    def _runs(self, block: TextBlock) -> Runs:
        return _block_runs(block, self.profile, self.keep_hyphen)

    def _cell(self, cell: TableCell | None) -> Cell:
        lines = cell_lines(cell, table_options(self.profile))
        options = TextOptions(keep_hyphen=self.keep_hyphen)
        return spans_to_runs([find_scripts(line.spans, self.profile) for line in lines], options)

    def heading(self, element: TextElement) -> None:
        headings = self.profile.headings
        runs = self._runs(element.block)
        text = plain_text(runs)
        found = re.match(headings.number, text)
        number = found["number"] if found else None
        if found:
            runs = drop_prefix(runs, len(text) - len(found["text"]))
        self._add(
            Heading(
                id=self._next_id("h"),
                level=headings.levels.index(element.role) + 1,
                runs=runs,
                number=number,
            ),
            element,
        )

    def paragraph(self, element: Element, runs: Runs, role: ParagraphRole) -> None:
        self._add(Paragraph(id=self._next_id("p"), runs=runs, role=role), element)

    def text(self, element: TextElement) -> None:
        role = element.role
        runs = self._runs(element.block)
        if role in self.profile.headings.levels:
            self.heading(element)
        elif role == "title":
            self.front["title"] = plain_text(runs)
        elif role in ("authors", "affiliation"):
            self.front[role] = plain_text(runs)
        elif role == "keywords":
            self.front["keywords"] = plain_text(runs)
        elif role == "abstract":
            self.abstract += runs
            self.paragraph(element, runs, "abstract")
        else:
            self.paragraph(element, runs, "small" if role == "small" else "body")

    def meta(self, element: MetaElement) -> None:
        metadata = self.profile.metadata
        runs = self._runs(element.block)
        text = plain_text(runs)
        for key, pattern in (
            ("citation", metadata.citation_block),
            ("copyright", metadata.copyright_block),
        ):
            found = re.match(pattern, text)
            if found:
                self.front[key] = text[found.end() :]
        self.paragraph(element, runs, "meta")

    def figure(self, element: FigureElement) -> None:
        figures = self.profile.figures
        asset = self.crop(
            page=element.page,
            bbox=element.crop_box,
            zoom=figures.zoom,
            grayscale=False,
            asset_id=f"figure-{element.number}",
        )
        self.assets[asset.id] = asset
        self._add(
            Figure(
                id=f"figure-{element.number}",
                number=element.number,
                asset=asset.id,
                caption=element.caption,
                alt=element.alt,
            ),
            element,
        )

    def table(self, element: TableElement) -> None:
        table = element.table
        self._add(
            Table(
                id=f"table-{element.number}",
                number=element.number or "",
                caption=element.caption,
                header=tuple(self._cell(cell) for cell in table.header),
                rows=tuple(tuple(self._cell(cell) for cell in row) for row in table.rows),
            ),
            element,
        )

    def equation(self, element: EquationElement) -> None:
        settings = self.profile.equations
        equation = element.equation
        block_id = self._next_id("equation")
        asset = self.crop(
            page=element.page,
            bbox=equation.bbox,
            zoom=settings.zoom,
            grayscale=settings.grayscale,
            asset_id=block_id,
        )
        self.assets[asset.id] = asset
        self._add(
            Equation(id=block_id, alt=equation.alt, number=equation.number, asset=asset.id),
            element,
        )

    def emit(self, element: Element) -> None:
        match element:
            case TextElement():
                self.text(element)
            case MetaElement():
                self.meta(element)
            case FigureElement():
                self.figure(element)
            case TableElement():
                self.table(element)
            case EquationElement():
                self.equation(element)


def document_vocabulary(pages: Iterable[PageData]) -> frozenset[str]:
    """Collect the words a paper uses whole, leaving out the pieces of words broken across lines."""
    pieces = []
    for page in pages:
        for block in page.blocks:
            broken = False
            for line in block.lines:
                text = clean_text("".join(span.text for span in line.spans)).strip()
                words = text.split()
                if broken and words:
                    words = words[1:]
                broken = text.endswith("-")
                if broken and words:
                    words = words[:-1]
                pieces.append(" ".join(words))
    return vocabulary(pieces)


def hyphen_rule(pages: Iterable[PageData], profile: Profile) -> KeepHyphen:
    if profile.text.line_end_hyphens == "keep":
        return lambda left, right: True
    return keep_hyphen_from_vocabulary(document_vocabulary(pages))


def _promote(doc: Document, profile: Profile) -> Document:
    """Turn paragraphs into list items and references, once paragraphs have been joined."""
    bullet = profile.text.bullet
    references = profile.references
    in_references = False
    blocks: list[Block] = []
    for block in doc.blocks:
        if isinstance(block, Heading):
            in_references = re.search(references.heading, plain_text(block.runs)) is not None
        if not isinstance(block, Paragraph):
            blocks.append(block)
            continue
        text = plain_text(block.runs)
        marker = re.match(bullet, text)
        if marker is not None:
            runs = drop_prefix(block.runs, marker.end())
            blocks.append(ListItem(id=block.id, runs=runs))
        elif in_references:
            found = re.search(references.doi, text)
            blocks.append(
                Reference(id=block.id, runs=block.runs, doi=found["doi"] if found else None)
            )
        else:
            blocks.append(block)
    return replace(doc, blocks=tuple(blocks))


def assemble(
    pages: Sequence[PageData],
    profile: Profile,
    *,
    crop: Crop,
    pdf_metadata: dict[str, str],
    problems: list[Problem] | None = None,
) -> Document:
    """Build the document from extracted pages. All rendering goes through `crop`.

    What the adapter can't place is added to `problems`, when the caller passes a list.
    """
    problems = problems if problems is not None else []
    keep_hyphen = hyphen_rule(pages, profile)
    elements = [e for page in pages for e in page_elements(page, profile, keep_hyphen, problems)]
    emitter = _Emitter(profile, keep_hyphen, crop)
    for element in join_tables(elements, profile):
        emitter.emit(element)

    front = FrontMatter(abstract=emitter.abstract, **emitter.front)
    doc = Document(
        meta=build_meta(front, pdf_metadata, profile),
        blocks=tuple(emitter.blocks),
        assets=emitter.assets,
        provenance=emitter.provenance,
    )
    doc = join_paragraphs(
        doc,
        ParagraphOptions(
            terminator=profile.text.paragraph_end,
            loose_roles=profile.text.loose_join_roles,
            starts_new=profile.text.bullet,
            keep_hyphen=keep_hyphen,
            reference_heading=profile.references.heading,
            entry_start=profile.references.entry_start,
        ),
    )
    return _promote(doc, profile)
