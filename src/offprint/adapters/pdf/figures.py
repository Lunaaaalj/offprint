"""Find the region of a figure from its caption, for templates that caption below the figure."""

from collections.abc import Sequence
from dataclasses import dataclass

from offprint.adapters.pdf.layout import Column, column_of, column_range
from offprint.cleanup.geometry import grow, touches, union
from offprint.ir import BBox
from offprint.profiles.schema import LabelRules, Profile


@dataclass(frozen=True, slots=True, kw_only=True)
class FigureRegion:
    bbox: BBox
    column: Column


def _top_bound(
    caption: BBox,
    column: Column,
    blocks: Sequence[BBox],
    captions: Sequence[BBox],
    profile: Profile,
) -> float:
    """Return the bottom of the nearest block or caption above, which bounds the figure."""
    figures = profile.figures
    above = [
        box[3]
        for box in blocks
        if box[3] <= caption[1] - figures.block_gap
        and (column == "full" or column_of(box, profile.page) in (column, "full"))
    ]
    # A caption above matters too: without it Fig. 2 swallows Fig. 1.
    above += [
        box[3]
        for box in captions
        if box[3] <= caption[1]
        and box[2] >= caption[0]
        and box[0] <= caption[0] + figures.caption_reach
    ]
    return max(above, default=profile.page.header_y)


def figure_region(
    caption: BBox,
    *,
    blocks: Sequence[BBox],
    captions: Sequence[BBox],
    graphics: Sequence[BBox],
    page_width: float,
    profile: Profile,
) -> FigureRegion:
    """Work out the crop for the figure above `caption`.

    `blocks` are the text blocks that bound a figure and `captions` the other captions on the page.
    The crop is the union of the shapes between the bound and the caption. The figure is full width
    if any of those shapes crosses the gutter, and otherwise sits in the caption's column.
    """
    figures, layout = profile.figures, profile.page

    def shapes_below(top: float) -> list[BBox]:
        return [
            box
            for box in graphics
            if box[3] <= caption[1] + figures.edge_tolerance
            and box[1] >= layout.header_y
            and box[2] - box[0] < page_width
            and box[1] >= top - figures.edge_tolerance
            and box[2] - box[0] > figures.min_graphic_size
            and box[3] - box[1] > figures.min_graphic_size
        ]

    column = column_of(caption, layout)
    top = _top_bound(caption, column, blocks, captions, profile)
    shapes = shapes_below(top)
    reach = figures.full_width_overlap
    if any(s[0] < layout.split_x - reach and s[2] > layout.split_x + reach for s in shapes):
        column = "full"
        top = _top_bound(caption, column, blocks, captions, profile)
        shapes = shapes_below(top)

    if shapes:
        box = grow(union(shapes), figures.crop_margin)
        bbox = (max(box[0], 0.0), max(box[1], 0.0), min(box[2], page_width), box[3])
    else:
        left, right = column_range(column, layout)
        bbox = (
            left,
            top + figures.fallback_top_margin,
            right,
            caption[1] - figures.fallback_bottom_margin,
        )
    return FigureRegion(bbox=bbox, column=column)


def include_labels(crop: BBox, texts: Sequence[tuple[BBox, int]], rules: LabelRules) -> BBox:
    """Grow a figure's crop to take in the short text blocks that touch it or sit close to it.

    `texts` are the page's text blocks as (box, word count). A drawn figure's labels are text, not
    shapes, so the union of the shapes leaves them out. A block next to a label counts too, but a
    block of more than `rules.max_words` words is a paragraph, whatever its place.
    """
    labels = [box for box, words in texts if words <= rules.max_words]
    grown = True
    while grown:
        grown = False
        for box in list(labels):
            if touches(grow(box, rules.gap), crop):
                crop = union((crop, box))
                labels.remove(box)
                grown = True
    return crop
