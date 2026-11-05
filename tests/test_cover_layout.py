"""The overflow and contrast checks as pure functions; test_cover_render.py runs them for real."""

import pytest
from PIL import Image

from offprint.cover.layout import (
    Element,
    contrast_problems,
    overflow_problems,
    worst_grayscale_contrast,
)

BOX = (100.0, 100.0, 500.0, 300.0)
WHITE = (255, 255, 255)


def element(name: str = "title", box=BOX, ink=(110.0, 110.0, 490.0, 290.0), colour=WHITE):
    return Element(name, box, ink, colour)


def codes(problems: list) -> list[str]:
    return [problem.code for problem in problems]


def test_text_inside_its_box_is_fine() -> None:
    assert overflow_problems([element()], 1600, 2560) == []


def test_sub_pixel_rounding_is_not_overflow() -> None:
    assert overflow_problems([element(ink=(99.8, 100.0, 500.2, 300.0))], 1600, 2560) == []


@pytest.mark.parametrize(
    "ink",
    [
        (90.0, 110.0, 490.0, 290.0),
        (110.0, 90.0, 490.0, 290.0),
        (110.0, 110.0, 510.0, 290.0),
        (110.0, 110.0, 490.0, 310.0),
    ],
    ids=["left", "top", "right", "bottom"],
)
def test_text_leaving_its_box_on_any_side_is_overflow(ink: tuple) -> None:
    assert codes(overflow_problems([element(ink=ink)], 1600, 2560)) == ["cover.overflow"]


def test_an_element_with_no_text_cannot_overflow() -> None:
    assert overflow_problems([element(ink=(0.0, 300.0, 0.0, 300.0))], 1600, 2560) == []


def test_a_box_leaving_the_page_is_overflow() -> None:
    box = (1500.0, 100.0, 1700.0, 300.0)

    problems = overflow_problems([element(box=box, ink=(1510.0, 110.0, 1520.0, 120.0))], 1600, 2560)

    assert codes(problems) == ["cover.overflow"]


def test_colliding_boxes_are_overflow() -> None:
    lower = element("authors", box=(100.0, 290.0, 500.0, 400.0), ink=(110.0, 295.0, 490.0, 390.0))

    assert codes(overflow_problems([element(), lower], 1600, 2560)) == ["cover.overflow"]


def test_touching_boxes_do_not_collide() -> None:
    lower = element("authors", box=(100.0, 300.0, 500.0, 400.0), ink=(110.0, 310.0, 490.0, 390.0))

    assert overflow_problems([element(), lower], 1600, 2560) == []


def test_black_on_white_is_the_maximum() -> None:
    assert worst_grayscale_contrast((0, 0, 0), Image.new("RGB", (4, 4), WHITE)) == pytest.approx(21)


def test_equal_luminance_colours_vanish_in_greyscale() -> None:
    """Red on green reads fine in colour and not at all on e-ink."""
    red, green = (255, 0, 0), (0, 130, 0)

    assert worst_grayscale_contrast(red, Image.new("RGB", (4, 4), green)) < 1.2


def test_the_closest_pixel_decides() -> None:
    background = Image.new("RGB", (4, 4), (0, 0, 0))
    background.putpixel((1, 1), (240, 240, 240))

    assert worst_grayscale_contrast(WHITE, background) < 1.3


def test_low_contrast_is_reported_for_the_element() -> None:
    page = Image.new("RGB", (600, 400), (200, 200, 200))

    problems = contrast_problems([element()], page)

    assert codes(problems) == ["cover.contrast"]
    assert "title" in problems[0].message


def test_only_the_pixels_behind_the_text_count() -> None:
    page = Image.new("RGB", (600, 400), (0, 0, 0))
    page.paste((255, 255, 255), (0, 0, 600, 100))

    assert contrast_problems([element()], page) == []


def test_text_off_the_page_is_read_only_where_it_is_on_the_page() -> None:
    page = Image.new("RGB", (600, 400), (0, 0, 0))

    assert contrast_problems([element(ink=(110.0, 110.0, 5000.0, 290.0))], page) == []


def test_empty_text_needs_no_contrast() -> None:
    page = Image.new("RGB", (600, 400), WHITE)

    assert contrast_problems([element(ink=(100.0, 100.0, 100.0, 100.0))], page) == []
