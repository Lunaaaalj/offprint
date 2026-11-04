"""What an adapter reads from a source before it becomes IR: the data cleanup steps work on.

This is the contract between adapters and `cleanup/`. It's library-neutral, so nothing here knows
about PyMuPDF, and template-neutral: the adapter fills `bold`, `italic` and `superscript` using its
profile, so cleanup steps never inspect font names. `font` and `size` are kept for grouping spans
that look alike. Coordinates are in page points, with the origin at the top left.
"""

from dataclasses import dataclass

from offprint.ir import BBox


@dataclass(frozen=True, slots=True, kw_only=True)
class Span:
    text: str
    bbox: BBox
    page: int  # 1-based, like Provenance.page.
    font: str = ""
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    superscript: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Line:
    spans: tuple[Span, ...]
    bbox: BBox


@dataclass(frozen=True, slots=True, kw_only=True)
class TextBlock:
    lines: tuple[Line, ...]
    bbox: BBox
    page: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TableCell:
    spans: tuple[Span, ...]
    bbox: BBox


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractedTable:
    """A detected table before cleanup. Rows may be uneven and a cell may be None (merged away)."""

    rows: tuple[tuple[TableCell | None, ...], ...]
    bbox: BBox
    page: int
