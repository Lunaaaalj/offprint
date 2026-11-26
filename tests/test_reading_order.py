"""reading_order keeps every element, including ones beside a full-width separator (#57)."""

from collections import Counter
from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from offprint.adapters.pdf.layout import Column, reading_order


@dataclass(frozen=True)
class Box:
    name: str
    column: Column
    top: float
    bottom: float


def names(boxes: list[Box]) -> list[str]:
    return [box.name for box in boxes]


def test_elements_level_with_a_separator_go_before_it():
    full = Box("full", "full", 234, 263)
    left = Box("left", "left", 234, 263)
    right = Box("right", "right", 234, 263)

    assert names(reading_order([full, left, right])) == ["left", "right", "full"]


def test_element_overlapping_a_separator_top_goes_before_it():
    full = Box("full", "full", 200, 260)
    left = Box("left", "left", 190, 215)

    assert names(reading_order([full, left])) == ["left", "full"]


def test_element_overlapping_a_separator_bottom_goes_after_it():
    full = Box("full", "full", 200, 260)
    right = Box("right", "right", 250, 280)

    assert names(reading_order([right, full])) == ["full", "right"]


def test_elements_clear_of_the_separator_keep_their_bands():
    left = Box("left", "left", 100, 120)
    full = Box("full", "full", 234, 263)
    right = Box("right", "right", 300, 320)

    assert names(reading_order([right, full, left])) == ["left", "full", "right"]


def test_band_reads_left_column_then_right():
    boxes = [
        Box("r1", "right", 100, 120),
        Box("l2", "left", 130, 150),
        Box("l1", "left", 100, 120),
        Box("full", "full", 200, 220),
        Box("r3", "right", 230, 250),
        Box("l3", "left", 240, 260),
    ]

    assert names(reading_order(boxes)) == ["l1", "l2", "r1", "full", "l3", "r3"]


@st.composite
def boxes(draw: st.DrawFn) -> list[Box]:
    count = draw(st.integers(min_value=0, max_value=12))
    result = []
    for index in range(count):
        column = draw(st.sampled_from(["left", "right", "full"]))
        top = draw(st.floats(min_value=0, max_value=800, allow_nan=False))
        height = draw(st.floats(min_value=0, max_value=200, allow_nan=False))
        result.append(Box(f"b{index}", column, top, top + height))
    return result


@given(boxes())
def test_reading_order_is_a_permutation(page: list[Box]):
    assert Counter(reading_order(page)) == Counter(page)
