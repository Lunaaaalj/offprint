"""What an adapter reads from a source before it becomes IR: the data cleanup steps work on.

This is the contract between adapters and `cleanup/`. It's library-neutral, so nothing here knows
about PyMuPDF, and template-neutral: the adapter fills `bold`, `italic` and `superscript` using its
profile, so cleanup steps never inspect font names. `font` and `size` are kept for grouping spans
that look alike. Coordinates are in page points, with the origin at the top left.
"""

from dataclasses import dataclass
from typing import Literal

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
    """A detected table. Rows may be uneven and a cell may be None (merged away).

    `header` stays empty until `join_header_rows` moves the header rows out of `rows`.
    """

    rows: tuple[tuple[TableCell | None, ...], ...]
    bbox: BBox
    page: int
    header: tuple[TableCell | None, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceText:
    """A piece of the source's reading text, with its line breaks already undone.

    A source without pages has neither `page` nor `bbox`, and says which `section` it's from.
    """

    text: str
    page: int | None = None
    bbox: BBox | None = None
    section: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCaption:
    kind: Literal["figure", "table"]
    number: str
    page: int | None = None
    bbox: BBox | None = None
    continued: bool = False
    """It's the "(Continued)" caption of a table's later piece, so it isn't a new table."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEquation:
    number: str
    page: int | None = None
    bbox: BBox | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEvidence:
    """What the source itself shows, read apart from the IR, for the QA gate to compare against.

    `pages` is `None` for a source that has none, such as JATS.
    """

    pages: int | None
    texts: tuple[SourceText, ...]
    captions: tuple[SourceCaption, ...]
    equations: tuple[SourceEquation, ...]
