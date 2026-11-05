"""Caption steps: put back together captions that a PDF scattered into pieces."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from offprint.cleanup.geometry import centre, grow, touches, union
from offprint.cleanup.registry import step
from offprint.extraction import Line, Span, TextBlock


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptionOptions:
    touch_gap: float = 2.0
    """Blocks closer than this count as touching (in points)."""
    line_tolerance: float = 2.5
    """Spans whose y-centres differ by at most this share a line (in points)."""


def _y_centre(span: Span) -> float:
    return centre(span.bbox)[1]


@step("regroup_lines", "caption")
def regroup_lines(spans: Iterable[Span], line_tolerance: float = 2.5) -> tuple[Line, ...]:
    """Regroup spans into lines by y-centre, then order each line by x."""
    lines: list[list[Span]] = []
    for span in sorted(spans, key=_y_centre):
        if lines and abs(_y_centre(span) - _y_centre(lines[-1][0])) <= line_tolerance:
            lines[-1].append(span)
        else:
            lines.append([span])
    return tuple(
        Line(
            spans=tuple(sorted(line, key=lambda span: span.bbox[0])),
            bbox=union(span.bbox for span in line),
        )
        for line in lines
    )


def _merged(group: Sequence[TextBlock], line_tolerance: float) -> TextBlock:
    spans = [span for block in group for line in block.lines for span in line.spans]
    return TextBlock(
        lines=regroup_lines(spans, line_tolerance),
        bbox=union(block.bbox for block in group),
        page=group[0].page,
    )


@step("merge_touching_blocks", "caption")
def merge_touching_blocks(
    blocks: Sequence[TextBlock], options: CaptionOptions | None = None
) -> tuple[TextBlock, ...]:
    """Merge caption pieces that touch, and put each result's spans back in reading order.

    Give this only caption-styled blocks. Blocks on different pages never merge.
    """
    options = options or CaptionOptions()
    groups = [[block] for block in blocks]
    merged = True
    while merged:
        merged = False
        for group in groups:
            box = grow(union(block.bbox for block in group), options.touch_gap)
            other = next(
                (
                    candidate
                    for candidate in groups
                    if candidate is not group
                    and candidate[0].page == group[0].page
                    and touches(box, union(block.bbox for block in candidate))
                ),
                None,
            )
            if other is not None:
                group += other
                groups = [candidate for candidate in groups if candidate is not other]
                merged = True
                break
    return tuple(_merged(group, options.line_tolerance) for group in groups)
