"""Caption steps, from `prototype/README.md` item 8 (Fig. 16 p. 18, Fig. 22 p. 25)."""

from offprint.cleanup import CaptionOptions, merge_touching_blocks, regroup_lines
from offprint.cleanup.geometry import union
from offprint.extraction import Line, Span, TextBlock


def span(text: str, x0: float, x1: float, y0: float = 100.0, y1: float = 108.0) -> Span:
    return Span(text=text, bbox=(x0, y0, x1, y1), page=1)


def block(*spans: Span, page: int = 1) -> TextBlock:
    bbox = union(s.bbox for s in spans)
    return TextBlock(lines=(Line(spans=spans, bbox=bbox),), bbox=bbox, page=page)


def lines_of(block: TextBlock) -> list[str]:
    return ["".join(s.text for s in line.spans) for line in block.lines]


def test_spans_regroup_into_lines_by_y_then_x() -> None:
    # The Fig. 16 failure: the pieces arrive in the wrong order inside the block.
    spans = [
        span("Grap", 100, 120, y0=100),
        span("second line", 50, 150, y0=110, y1=118),
        span("FIGU", 50, 70, y0=100),
        span("RE 16 ", 70, 100, y0=100),
    ]

    assert [[s.text for s in line.spans] for line in regroup_lines(spans)] == [
        ["FIGU", "RE 16 ", "Grap"],
        ["second line"],
    ]


def test_spans_on_nearby_lines_stay_on_separate_lines() -> None:
    spans = [span("one", 0, 10, y0=100, y1=108), span("two", 0, 10, y0=103, y1=111)]

    assert len(regroup_lines(spans)) == 2


def test_the_tolerance_is_an_argument() -> None:
    spans = [span("one", 0, 10, y0=100, y1=108), span("two", 12, 20, y0=103, y1=111)]

    assert len(regroup_lines(spans, line_tolerance=4)) == 1


def test_a_line_bbox_covers_its_spans() -> None:
    line = regroup_lines([span("a", 10, 20), span("b", 30, 40)])[0]

    assert line.bbox == (10, 100, 40, 108)


def test_touching_fragments_merge_in_reading_order() -> None:
    blocks = [
        block(span("hical summary", 121, 200)),
        block(span("FIGU", 50, 70)),
        block(span("RE 16 ", 70, 100)),
        block(span("Grap", 101, 120)),
    ]

    merged = merge_touching_blocks(blocks)

    assert len(merged) == 1
    assert lines_of(merged[0]) == ["FIGURE 16 Graphical summary"]
    assert merged[0].bbox == (50, 100, 200, 108)


def test_touching_chains_merge_transitively() -> None:
    blocks = [block(span("a", 0, 10)), block(span("c", 22, 30)), block(span("b", 11, 21))]

    assert lines_of(merge_touching_blocks(blocks)[0]) == ["abc"]


def test_separate_captions_stay_separate() -> None:
    blocks = [block(span("FIGURE 1", 50, 100)), block(span("FIGURE 2", 300, 350))]

    assert len(merge_touching_blocks(blocks)) == 2


def test_the_gap_is_an_option() -> None:
    blocks = [block(span("a", 0, 10)), block(span("b", 13, 20))]

    assert len(merge_touching_blocks(blocks)) == 2
    assert len(merge_touching_blocks(blocks, CaptionOptions(touch_gap=4))) == 1


def test_blocks_on_different_pages_never_merge() -> None:
    blocks = [block(span("a", 0, 10)), block(span("b", 0, 10), page=2)]

    assert [b.page for b in merge_touching_blocks(blocks)] == [1, 2]


def test_a_block_alone_still_gets_its_spans_sorted() -> None:
    single = block(span("second", 60, 100), span("first ", 10, 59))

    assert lines_of(merge_touching_blocks([single])[0]) == ["first second"]
