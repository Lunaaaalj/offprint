"""Choose the figure a cover is built around, and treat it into a duotone.

The default choice prefers a photo-like figure, then a diagram, then nothing. Charts never
qualify: a plot means nothing once it's a duotone. Pass another `HeroSelector` through
`CoverOptions.select_hero` to use a different rule.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from itertools import product
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from offprint.ir import Asset, Document, Figure

logger = logging.getLogger(__name__)

type Kind = Literal["photo", "diagram", "chart"]

SHADOW = (15, 27, 45)  # The cover's background too (see cover.css), so a hero dissolves into it.
HIGHLIGHT = (214, 236, 232)
HERO_BOX = (1300, 1340)

MIN_SIDE = 200  # Smaller than this is an icon, and would turn to mush at cover size.
ANALYSIS_SIDE = 512
TONE_BINS = 32
FOREGROUND_DELTA = 12  # Grey levels away from the background.

# The median tone step between neighbouring foreground pixels tells the kinds apart: flat fills
# barely change, line art jumps, and natural texture sits in between.
PHOTO_EDGES = (6, 30)
PHOTO_MIN_FOREGROUND = 0.25
FLAT_STEP = 3
LINE_ART_MAX_FLAT = 0.1  # Plots of lines have almost no filled areas, unlike a boxed diagram.

LONG_LINE = 0.6  # A row or column that's at least this much foreground holds a long line.
THIN_LINE = 3  # Pixels. Thicker runs are filled shapes, not rules.
MIN_GRIDLINES = 4
GRID_SPACING_SPREAD = 0.25
EDGE_BAND = 0.03  # A rule this close to the image's edge is a frame, not an axis.
AXIS_REACH = 0.8
AXIS_OVERRUN = 0.3

PANEL_MIN_WIDTH = 0.15
BLANK_TONE = 8  # Grey levels from a line's median.
BLANK_SHARE = 0.9  # Allows for a panel letter sitting in a margin.
PANEL_TIE = 0.9  # Scores this close aren't a real difference between panels.
LABEL_CORNER = 0.2  # Of the shorter side. Panel letters sit in the corners.
LABEL_TONE = 200
DARK_CORNER = 64
TONE_CUTOFF = (0.5, 2.5)  # Percent clipped from each end, so a white label can't dim the image.


@dataclass(frozen=True, slots=True)
class Assessment:
    kind: Kind
    score: float


@dataclass(frozen=True, slots=True)
class Hero:
    image: Image.Image
    figure_id: str
    kind: Kind


type HeroSelector = Callable[[Document], Hero | None]


def _thin_line_positions(share: np.ndarray) -> list[float]:
    """Find the centres of thin runs of rows (or columns) that are mostly foreground."""
    rows = np.flatnonzero(share >= LONG_LINE)
    if rows.size == 0:
        return []
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    return [float(run.mean()) for run in runs if run.size <= THIN_LINE]


def _is_evenly_spaced(positions: list[float]) -> bool:
    if len(positions) < MIN_GRIDLINES:
        return False
    gaps = np.diff(positions)
    return float(gaps.std() / gaps.mean()) <= GRID_SPACING_SPREAD


def _has_axes(foreground: np.ndarray) -> bool:
    """Look for an L of two long rules, the vertical one stopping at the horizontal one."""
    height, width = foreground.shape
    rows = _thin_line_positions(foreground.mean(axis=1))
    columns = _thin_line_positions(foreground.mean(axis=0))
    for row, column in product(rows, columns):
        y, x = round(row), round(column)
        if not (height * 0.6 < y < height * (1 - EDGE_BAND)):
            continue
        if not (width * EDGE_BAND < x < width * 0.4):
            continue
        above = foreground[: y - THIN_LINE, x - 1 : x + 2].any(axis=1)
        below = foreground[y + THIN_LINE :, x - 1 : x + 2].any(axis=1)
        right = foreground[y - 1 : y + 2, x + THIN_LINE :].any(axis=0)
        if (
            above[above.size // 4 :].mean() >= AXIS_REACH
            and right.mean() >= AXIS_REACH
            and (below.size == 0 or below.mean() <= AXIS_OVERRUN)
        ):
            return True
    return False


def assess(image: Image.Image) -> Assessment:
    """Classify an image by its pixels, and score how much picture it has to show."""
    thumbnail = image.convert("L")
    thumbnail.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE), Image.Resampling.LANCZOS)
    grey = np.asarray(thumbnail, dtype=float)

    tones = np.histogram(grey, bins=TONE_BINS, range=(0, 256))[0] / grey.size
    background_bin = int(tones.argmax())
    background = (background_bin + 0.5) * 256 / TONE_BINS
    foreground = np.abs(grey - background) > FOREGROUND_DELTA
    share = float(foreground.mean())

    others = np.delete(tones, background_bin)
    others = others[others > 0] / max(others.sum(), 1e-9)
    entropy = float(-(others * np.log2(others)).sum())
    score = share * entropy

    steps = np.abs(np.diff(grey, axis=1))[:-1, :] + np.abs(np.diff(grey, axis=0))[:, :-1]
    inked = foreground[:-1, :-1]
    edge = float(np.median(steps[inked])) if inked.any() else 0.0
    flat = float((steps[inked] < FLAT_STEP).mean()) if inked.any() else 1.0

    if PHOTO_EDGES[0] <= edge <= PHOTO_EDGES[1] and share >= PHOTO_MIN_FOREGROUND:
        return Assessment("photo", score)
    gridded = _is_evenly_spaced(_thin_line_positions(foreground.mean(axis=1)))
    if flat <= LINE_ART_MAX_FLAT or gridded or _has_axes(foreground):
        return Assessment("chart", score)
    return Assessment("diagram", score)


def _decode(asset: Asset) -> Image.Image | None:
    """Open an asset as RGB on white, or return None if it isn't a raster image."""
    try:
        with Image.open(BytesIO(asset.bytes)) as source:
            rgba = source.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        logger.warning("cover: skipping asset %s: %s", asset.id, error)
        return None
    canvas = Image.new("RGBA", rgba.size, "white")
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def _spans(busy: np.ndarray) -> list[tuple[int, int]]:
    """Return the [start, end) of each run of True."""
    edges = np.flatnonzero(np.diff(np.concatenate(([False], busy, [False])).astype(int)))
    return [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2], strict=True)]


def _blank_lines(grey: np.ndarray, axis: int) -> np.ndarray:
    """Mark the lines along `axis` that are all one tone."""
    medians = np.median(grey, axis=axis, keepdims=True)
    return (np.abs(grey - medians) <= BLANK_TONE).mean(axis=axis) >= BLANK_SHARE


def _erase_corner_labels(image: Image.Image) -> Image.Image:
    """Paint out the light tags ("A", "B") that sit in the corners of dark panels."""
    grey = np.asarray(image.convert("L"))
    pixels = np.array(image)
    height, width = grey.shape
    side = round(min(height, width) * LABEL_CORNER)
    for rows, columns in product(
        (slice(0, side), slice(height - side, height)),
        (slice(0, side), slice(width - side, width)),
    ):
        corner = grey[rows, columns]
        if np.median(corner) < DARK_CORNER:
            pixels[rows, columns][corner > LABEL_TONE] = np.median(corner)
    return Image.fromarray(pixels)


def crop_to_panel(image: Image.Image) -> Image.Image:
    """Crop a multi-panel figure to its best panel, since side-by-side panels fight on a cover.

    Panels are the runs of columns between blank gutters. A single-panel image just loses its
    blank margins.
    """
    grey = np.asarray(image.convert("L"), dtype=float)
    minimum = max(int(image.width * PANEL_MIN_WIDTH), 1)
    panels = [span for span in _spans(~_blank_lines(grey, axis=0)) if span[1] - span[0] >= minimum]
    if not panels:
        return image
    crops = []
    for left, right in panels:
        rows = _spans(~_blank_lines(grey[:, left:right], axis=1))
        top, bottom = max(rows, key=lambda row: row[1] - row[0], default=(0, image.height))
        crops.append(image.crop((left, top, right, bottom)))

    scores = [assess(crop).score for crop in crops]
    close = [i for i, score in enumerate(scores) if score >= max(scores) * PANEL_TIE]
    middle = (len(crops) - 1) / 2
    return _erase_corner_labels(crops[min(close, key=lambda i: abs(i - middle))])


def select_hero(doc: Document) -> Hero | None:
    """Pick the best photo, else the best diagram, else None. This is the default selector."""
    best: dict[Kind, tuple[float, Hero]] = {}
    for block in doc.blocks:
        if not isinstance(block, Figure) or block.asset not in doc.assets:
            continue
        image = _decode(doc.assets[block.asset])
        if image is None or min(image.size) < MIN_SIDE:
            continue
        assessment = assess(image)
        kind = assessment.kind
        if kind != "chart" and (kind not in best or assessment.score > best[kind][0]):
            best[kind] = (assessment.score, Hero(image, block.id, kind))

    if "photo" in best:
        hero = best["photo"][1]
        return Hero(crop_to_panel(hero.image), hero.figure_id, hero.kind)
    return best["diagram"][1] if "diagram" in best else None


def _has_light_background(grey: np.ndarray) -> bool:
    edge = np.concatenate((grey[0], grey[-1], grey[:, 0], grey[:, -1]))
    return float(np.median(edge)) > 128


def treat_hero(image: Image.Image) -> Image.Image:
    """Duotone an image and fade it into the cover's background with an elliptical vignette."""
    grey = ImageOps.autocontrast(image.convert("L"), cutoff=TONE_CUTOFF)
    if _has_light_background(np.asarray(grey)):  # A white figure would be a glaring rectangle.
        grey = ImageOps.invert(grey)
    scale = min(HERO_BOX[0] / grey.width, HERO_BOX[1] / grey.height)
    size = (round(grey.width * scale), round(grey.height * scale))
    grey = grey.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(1.0))

    tone = np.asarray(grey, dtype=float) / 255
    shadow, highlight = np.array(SHADOW, dtype=float), np.array(HIGHLIGHT, dtype=float)
    colour = shadow + (highlight - shadow) * tone[..., None] ** 1.15

    height, width = tone.shape
    ys, xs = np.mgrid[0:height, 0:width]
    radius = np.hypot((xs - width / 2) / (width / 2), (ys - height / 2) / (height / 2))
    fade = np.clip((1.0 - radius) / 0.28, 0, 1)[..., None] ** 1.4
    return Image.fromarray((shadow + (colour - shadow) * fade).astype(np.uint8))
