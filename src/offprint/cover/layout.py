"""Check a rendered cover from what the browser reports: boxes, ink and computed colours."""

from dataclasses import dataclass

import numpy as np
from PIL import Image

from offprint.ir import Problem

MIN_CONTRAST = 4.5  # WCAG AA for body text.
TOLERANCE = 0.5  # Sub-pixel rounding in reported boxes.

type Rect = tuple[float, float, float, float]  # left, top, right, bottom


@dataclass(frozen=True, slots=True)
class Element:
    """One text element: the box it was given, the box its text takes, and its colour."""

    name: str
    box: Rect
    ink: Rect
    colour: tuple[int, int, int]


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        inner[0] >= outer[0] - TOLERANCE
        and inner[1] >= outer[1] - TOLERANCE
        and inner[2] <= outer[2] + TOLERANCE
        and inner[3] <= outer[3] + TOLERANCE
    )


def _overlap(a: Rect, b: Rect) -> bool:
    return (
        min(a[2], b[2]) - max(a[0], b[0]) > TOLERANCE
        and min(a[3], b[3]) - max(a[1], b[1]) > TOLERANCE
    )


def overflow_problems(elements: list[Element], width: int, height: int) -> list[Problem]:
    """Report `cover.overflow`: text leaves its box, a box leaves the page, or boxes collide."""
    page: Rect = (0, 0, width, height)
    problems = [
        Problem("cover.overflow", f"{element.name}: text {element.ink} outside box {element.box}")
        for element in elements
        if element.ink[2] > element.ink[0] and not _contains(element.box, element.ink)
    ]
    problems += [
        Problem("cover.overflow", f"{element.name}: box {element.box} outside the page")
        for element in elements
        if not _contains(page, element.box)
    ]
    problems += [
        Problem("cover.overflow", f"{first.name} overlaps {second.name}")
        for i, first in enumerate(elements)
        for second in elements[i + 1 :]
        if _overlap(first.box, second.box)
    ]
    return problems


def _luminance(grey: np.ndarray) -> np.ndarray:
    level = grey / 255
    return np.where(level <= 0.04045, level / 12.92, ((level + 0.055) / 1.055) ** 2.4)


def worst_grayscale_contrast(colour: tuple[int, int, int], background: Image.Image) -> float:
    """Return the WCAG contrast of `colour` against `background`'s closest pixel, both in grey."""
    grey_ink = Image.new("RGB", (1, 1), colour).convert("L").getpixel((0, 0))
    ink = _luminance(np.array(grey_ink, dtype=float))
    pixels = _luminance(np.unique(np.asarray(background.convert("L"))).astype(float))
    ratios = (np.maximum(ink, pixels) + 0.05) / (np.minimum(ink, pixels) + 0.05)
    return float(ratios.min())


def contrast_problems(elements: list[Element], bare_page: Image.Image) -> list[Problem]:
    """Report `cover.contrast`: text unreadable on e-ink. `bare_page` is the cover without text."""
    problems = []
    for element in elements:
        left, top = max(round(element.ink[0]), 0), max(round(element.ink[1]), 0)
        right = min(round(element.ink[2]), bare_page.width)
        bottom = min(round(element.ink[3]), bare_page.height)
        if right <= left or bottom <= top:
            continue  # No text on the page, so nothing to read.
        ratio = worst_grayscale_contrast(element.colour, bare_page.crop((left, top, right, bottom)))
        if ratio < MIN_CONTRAST:
            problems.append(
                Problem("cover.contrast", f"{element.name}: {ratio:.1f}:1 in grayscale")
            )
    return problems
