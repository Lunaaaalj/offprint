"""Small helpers on bounding boxes, shared by the cleanup steps and the adapters."""

from collections.abc import Iterable

from offprint.ir import BBox


def union(boxes: Iterable[BBox]) -> BBox:
    """Return the smallest box holding all of `boxes`, which must not be empty."""
    x0, y0, x1, y1 = zip(*boxes, strict=True)
    return (min(x0), min(y0), max(x1), max(y1))


def grow(box: BBox, margin: float) -> BBox:
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def area(box: BBox) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection_area(a: BBox, b: BBox) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def touches(a: BBox, b: BBox) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def centre(box: BBox) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def contains_point(box: BBox, point: tuple[float, float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def horizontal_overlap(a: BBox, b: BBox) -> float:
    """Return how much of `a`'s width lies over `b`, from 0 to 1."""
    width = a[2] - a[0]
    if width <= 0:
        return 0.0
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) / width
