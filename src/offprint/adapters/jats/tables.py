"""HTML-like `<table>` to the IR's rectangular header and rows. Pure, apart from the problems."""

from collections.abc import Sequence
from dataclasses import dataclass

from offprint.adapters.jats.inline import inline_runs
from offprint.adapters.jats.xml import Element, local
from offprint.ir import Cell, Problem, Text

# HTML's own limit. The attributes are untrusted, and every extra column costs memory.
_MAX_COLSPAN = 1000


@dataclass(frozen=True, slots=True)
class RawCell:
    runs: Cell
    rowspan: int = 1
    colspan: int = 1


def expand_spans(rows: Sequence[Sequence[RawCell]], *, repeat_columns: bool) -> list[list[Cell]]:
    """Give every row one cell per column.

    A cell spanning rows is repeated, because each row must read on its own on a small screen.
    Header cells spanning columns repeat too, so no column loses its name. A body cell spanning
    columns is usually a subheading, which would read as a stutter, so it appears once.
    """
    grid: list[list[Cell]] = []
    # Column -> the cell still spanning into it, and how many more rows it covers.
    carried: dict[int, tuple[Cell, int]] = {}
    for row in rows:
        expanded: list[Cell] = []
        cells = iter(row)
        while True:
            column = len(expanded)
            if column in carried:
                runs, remaining = carried[column]
                expanded.append(runs)
                if remaining > 1:
                    carried[column] = (runs, remaining - 1)
                else:
                    del carried[column]
                continue
            cell = next(cells, None)
            if cell is None:
                break
            for offset in range(cell.colspan):
                content = cell.runs if repeat_columns or offset == 0 else ()
                expanded.append(content)
                if cell.rowspan > 1:
                    carried[column + offset] = (content, cell.rowspan - 1)
        grid.append(expanded)
    return grid


def merge_header(rows: Sequence[Sequence[Cell]]) -> tuple[Cell, ...]:
    """Fold several header rows into one, reading each column from the top."""
    if not rows:
        return ()
    merged: list[Cell] = []
    for column in zip(*rows, strict=True):
        cell: list = []
        previous = None
        for runs in column:
            if runs and runs != previous:
                cell.extend((Text(" "), *runs) if cell else runs)
            previous = runs
        merged.append(tuple(cell))
    return tuple(merged)


def read_table(
    table: Element, problems: list[Problem]
) -> tuple[tuple[Cell, ...], list[list[Cell]]]:
    """The header and rows of a `<table>`, all the same width.

    The rows of each section expand separately: a rowspan never crosses from `thead` to `tbody`.
    Without a `thead`, the first row becomes the header, because the IR's header isn't optional.
    """
    head = [_cells(row, problems) for row in _section_rows(table, "thead")]
    body = [
        _cells(row, problems)
        for section in ("tbody", "tfoot")
        for row in _section_rows(table, section)
    ]
    body += [_cells(row, problems) for row in table.findall("tr")]
    header_grid = expand_spans(head, repeat_columns=True)
    grid = expand_spans(body, repeat_columns=False)
    width = max((len(row) for row in (*header_grid, *grid)), default=0)
    header_grid = [_pad(row, width) for row in header_grid]
    grid = [_pad(row, width) for row in grid]
    if header_grid:
        return merge_header(header_grid), grid
    if grid:
        return tuple(grid[0]), grid[1:]
    return (), []


def _section_rows(table: Element, section: str) -> list[Element]:
    return [row for found in table.findall(section) for row in found.findall("tr")]


def _cells(row: Element, problems: list[Problem]) -> list[RawCell]:
    return [
        RawCell(
            inline_runs(cell, problems),
            rowspan=_span(cell, "rowspan", 1 << 16),
            colspan=_span(cell, "colspan", _MAX_COLSPAN),
        )
        for cell in row
        if local(cell) in ("td", "th")
    ]


def _span(cell: Element, attribute: str, limit: int) -> int:
    try:
        value = int(cell.get(attribute, "1"))
    except ValueError:
        return 1
    return min(max(value, 1), limit)


def _pad(row: list[Cell], width: int) -> list[Cell]:
    return row + [()] * (width - len(row))
