"""Page layout: which column a box is in, and the order a reader goes through a page."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from offprint.ir import BBox
from offprint.profiles.schema import PageLayout, Range

type Column = Literal["left", "right", "full"]


class Placed(Protocol):
    """Anything on a page that has a column and a vertical extent."""

    @property
    def column(self) -> Column: ...

    @property
    def top(self) -> float: ...

    @property
    def bottom(self) -> float: ...


@dataclass(frozen=True, slots=True)
class _Band:
    top: float
    bottom: float


def column_of(box: BBox, layout: PageLayout) -> Column:
    """A box that crosses the gutter by the margin on both sides is full width.

    In a single-column layout every box is.
    """
    split_x, margin = layout.split_x, layout.full_width_margin
    if split_x is None or margin is None:
        return "full"
    if box[0] < split_x - margin and box[2] > split_x + margin:
        return "full"
    return "left" if (box[0] + box[2]) / 2 < split_x else "right"


def column_range(column: Column, layout: PageLayout) -> Range:
    ranges = {"left": layout.left, "right": layout.right, "full": layout.full}
    return ranges[column] or layout.full


def reading_order[T: Placed](elements: Sequence[T]) -> list[T]:
    """Order a page's elements: full-width ones cut it into bands, read left column then right."""
    wide = sorted((e for e in elements if e.column == "full"), key=lambda e: e.top)
    narrow = [e for e in elements if e.column != "full"]
    ordered: list[T] = []
    start = float("-inf")
    for separator in [*wide, None]:
        end = separator.top if separator is not None else float("inf")
        band = [e for e in narrow if start <= (e.top + e.bottom) / 2 < end]
        ordered += sorted((e for e in band if e.column == "left"), key=lambda e: e.top)
        ordered += sorted((e for e in band if e.column == "right"), key=lambda e: e.top)
        if separator is not None:
            ordered.append(separator)
            start = separator.bottom
    return ordered
