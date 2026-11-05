"""Table steps: turn what table detection found into rows and columns a reader would recognise.

The steps run on `ExtractedTable`, whose cells hold spans, so joining cells never loses styling and
text is only built at the end. `cell_lines` gives the adapter a cell's spans in reading order.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from offprint.cleanup.captions import regroup_lines
from offprint.cleanup.geometry import (
    area,
    centre,
    contains_point,
    horizontal_overlap,
    intersection_area,
    union,
)
from offprint.cleanup.registry import step
from offprint.cleanup.text import clean_text, separate_words
from offprint.extraction import ExtractedTable, Line, Span, TableCell
from offprint.ir import BBox

type Row = tuple[TableCell | None, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TableOptions:
    line_tolerance: float = 2.5
    """Spans whose y-centres differ by at most this share a line (in points)."""
    word_gap: float = 1.0
    """Two spans further apart than this on a line are separate words (in points)."""
    reference_headers: tuple[str, ...] = ("References",)
    """A table whose first header is one of these lists references, one per row."""
    year_pattern: str = r"\d{4}[a-z]?\)?\s*$"
    """A reference table's first cell is finished once it matches this."""


def cell_lines(cell: TableCell | None, options: TableOptions | None = None) -> tuple[Line, ...]:
    """Return a cell's spans as lines in reading order, skipping whitespace-only spans."""
    if cell is None:
        return ()
    options = options or TableOptions()
    lines = regroup_lines((s for s in cell.spans if s.text.strip()), options.line_tolerance)
    return tuple(
        replace(line, spans=separate_words(line.spans, options.word_gap)) for line in lines
    )


def cell_text(cell: TableCell | None, options: TableOptions | None = None) -> str:
    lines = cell_lines(cell, options)
    text = " ".join("".join(span.text for span in line.spans) for line in lines)
    return clean_text(text).strip()


def _join_cells(first: TableCell | None, second: TableCell | None) -> TableCell | None:
    if first is None or second is None:
        return first or second
    return TableCell(spans=first.spans + second.spans, bbox=union((first.bbox, second.bbox)))


def _pad(row: Row, width: int) -> Row:
    return row + (None,) * (width - len(row))


def _join_rows(first: Row, second: Row) -> Row:
    width = max(len(first), len(second))
    pairs = zip(_pad(first, width), _pad(second, width), strict=True)
    return tuple(_join_cells(a, b) for a, b in pairs)


def _is_empty(cell: TableCell | None) -> bool:
    return cell is None or not any(span.text.strip() for span in cell.spans)


def _row_is_empty(row: Row) -> bool:
    return all(_is_empty(cell) for cell in row)


def _width(table: ExtractedTable) -> int:
    return max((len(row) for row in (table.header, *table.rows)), default=0)


@step("trim_swallowed_column", "table")
def trim_swallowed_column(
    table: ExtractedTable,
    text_boxes: Sequence[BBox],
    *,
    split_x: float,
    min_overlap: float = 0.6,
    margin: float = 5.0,
) -> ExtractedTable | None:
    """Undo a detection that took the neighbouring text column for a table column.

    `text_boxes` are the blocks of running text on the page and `split_x` is the gutter. If the
    table crosses the gutter and covers a text box, only the cells on the side without text stay.
    Returns None if no cell is left.
    """
    box = table.bbox
    covered = [t for t in text_boxes if intersection_area(box, t) > min_overlap * area(t)]
    if not (box[0] < split_x < box[2]) or not covered:
        return table

    keep_right = any(t[2] < split_x for t in covered)

    def keep(cell: TableCell | None) -> TableCell | None:
        if cell is None:
            return None
        on_the_kept_side = (
            cell.bbox[0] >= split_x - margin if keep_right else cell.bbox[2] <= split_x + margin
        )
        return cell if on_the_kept_side else None

    rows = tuple(tuple(keep(cell) for cell in row) for row in table.rows)
    kept = [cell.bbox for row in rows for cell in row if cell is not None]
    if not kept:
        return None
    left, _, right, _ = union(kept)
    return replace(table, rows=rows, bbox=(left, box[1], right, box[3]))


@step("fill_cells_from_spans", "table")
def fill_cells_from_spans(table: ExtractedTable, spans: Sequence[Span]) -> ExtractedTable:
    """Fill each cell with the spans centred inside its box, so words keep their real spaces."""

    def filled(cell: TableCell | None) -> TableCell | None:
        if cell is None:
            return None
        inside = tuple(
            span
            for span in spans
            if span.page == table.page and contains_point(cell.bbox, centre(span.bbox))
        )
        return TableCell(spans=inside, bbox=cell.bbox)

    return replace(table, rows=tuple(tuple(filled(cell) for cell in row) for row in table.rows))


@step("join_header_rows", "table")
def join_header_rows(table: ExtractedTable, is_header: Callable[[Span], bool]) -> ExtractedTable:
    """Move the consecutive header rows at the top of a table into one header, column by column.

    A row is a header when every span in it satisfies `is_header`. Blank rows are dropped.
    """

    def row_is_header(row: Row) -> bool:
        spans = [s for cell in row if cell is not None for s in cell.spans if s.text.strip()]
        return all(is_header(span) for span in spans)

    rows = [row for row in table.rows if not _row_is_empty(row)]
    count = 0
    while count < len(rows) and row_is_header(rows[count]):
        count += 1

    header = table.header
    for row in rows[:count]:
        header = _join_rows(header, row)
    return replace(table, header=header, rows=tuple(rows[count:]))


@step("join_wrapped_rows", "table")
def join_wrapped_rows(table: ExtractedTable, options: TableOptions | None = None) -> ExtractedTable:
    """Join rows that detection split per text line into the row they belong to.

    A row is a continuation if its first cell is empty, or, in a reference table, if the previous
    row's first cell doesn't have its year yet.
    """
    options = options or TableOptions()
    is_reference_table = bool(table.header) and (
        cell_text(table.header[0], options) in options.reference_headers
    )

    def unfinished(row: Row) -> bool:
        first = cell_text(row[0] if row else None, options)
        return re.search(options.year_pattern, first) is None

    rows: list[Row] = []
    for row in table.rows:
        if _row_is_empty(row):
            continue
        wrapped = _is_empty(row[0]) or (is_reference_table and rows and unfinished(rows[-1]))
        if rows and wrapped:
            rows[-1] = _join_rows(rows[-1], row)
        else:
            rows.append(row)
    return replace(table, rows=tuple(rows))


@step("merge_phantom_columns", "table")
def merge_phantom_columns(table: ExtractedTable) -> ExtractedTable:
    """Fold each column with an empty header into the neighbour with fewer conflicts.

    A conflict is a row where both columns hold text, and ties go left. A table without a header
    gives no way to tell a phantom column, so it's left alone, as is a column with no named
    neighbour.
    """
    if not table.header:
        return table
    width = _width(table)
    header = list(_pad(table.header, width))
    rows = [list(_pad(row, width)) for row in table.rows]

    def conflicts(first: int, second: int) -> int:
        return sum(1 for row in rows if not (_is_empty(row[first]) or _is_empty(row[second])))

    column = 0
    while column < len(header):
        named = [
            index
            for index in (column - 1, column + 1)
            if 0 <= index < len(header) and not _is_empty(header[index])
        ]
        if not _is_empty(header[column]) or not named:
            column += 1
            continue
        target = min(named, key=lambda index: conflicts(column, index))
        for row in rows:
            row[target] = _join_cells(row[target], row[column])
            del row[column]
        del header[column]
    return replace(table, header=tuple(header), rows=tuple(tuple(row) for row in rows))


def _same_text(first: Row, second: Row, options: TableOptions) -> bool:
    width = max(len(first), len(second))
    return [cell_text(cell, options) for cell in _pad(first, width)] == [
        cell_text(cell, options) for cell in _pad(second, width)
    ]


@step("join_continued_tables", "table")
def join_continued_tables(
    tables: Sequence[ExtractedTable],
    continued: Sequence[bool],
    options: TableOptions | None = None,
) -> tuple[ExtractedTable, ...]:
    """Append each table marked in `continued` to the one before it, skipping a repeated header.

    A different header on a continuation isn't a repeat, so it stays as a row and no text is lost.
    The result keeps the first piece's page, bbox and header.
    """
    options = options or TableOptions()
    joined: list[ExtractedTable] = []
    for table, is_continuation in zip(tables, continued, strict=True):
        if not (is_continuation and joined):
            joined.append(table)
            continue
        first = joined[-1]
        rows = list(table.rows)
        if table.header and not _same_text(table.header, first.header, options):
            rows.insert(0, table.header)
        if rows and first.header and _same_text(rows[0], first.header, options):
            del rows[0]
        joined[-1] = replace(first, rows=(*first.rows, *rows))
    return tuple(joined)


@step("square_rows", "table")
def square_rows(table: ExtractedTable) -> ExtractedTable:
    """Pad short rows and the header with empty cells, so every row is equally wide."""
    width = _width(table)
    return replace(
        table,
        header=_pad(table.header, width),
        rows=tuple(_pad(row, width) for row in table.rows),
    )


@step("pair_captions", "table")
def pair_captions(
    captions: Sequence[BBox],
    tables: Sequence[BBox],
    *,
    side: Literal["above", "below"] = "above",
    y_tolerance: float = 2.0,
) -> tuple[int | None, ...]:
    """Pair each caption with a table on its page, returning table indexes (None for no table).

    `side` says where captions sit relative to their table. Among the tables on that side that
    overlap the caption horizontally the nearest wins, and tables equally near go by how much they
    overlap. That's what separates two tables starting at the same y. A table is paired once.
    """

    def gap(caption: BBox, table: BBox) -> float:
        return table[1] - caption[3] if side == "above" else caption[1] - table[3]

    taken: set[int] = set()
    pairs: list[int | None] = []
    for caption in captions:
        candidates = [
            index
            for index, table in enumerate(tables)
            if index not in taken
            and gap(caption, table) >= -y_tolerance
            and horizontal_overlap(caption, table) > 0
        ]
        if not candidates:
            pairs.append(None)
            continue
        nearest = min(gap(caption, tables[index]) for index in candidates)
        tied = [i for i in candidates if gap(caption, tables[i]) <= nearest + y_tolerance]
        best = max(tied, key=lambda index: horizontal_overlap(caption, tables[index]))
        taken.add(best)
        pairs.append(best)
    return tuple(pairs)
