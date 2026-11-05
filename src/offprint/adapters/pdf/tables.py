"""Run the generic table steps on one page's detections, as this template needs them."""

from collections.abc import Sequence

from offprint.adapters.pdf.roles import classify, first_span
from offprint.cleanup import (
    TableOptions,
    fill_cells_from_spans,
    join_header_rows,
    join_wrapped_rows,
    merge_phantom_columns,
    trim_swallowed_column,
)
from offprint.cleanup.geometry import area, intersection_area
from offprint.extraction import ExtractedTable, Span, TextBlock
from offprint.ir import BBox
from offprint.profiles.schema import Profile


def table_options(profile: Profile) -> TableOptions:
    tables = profile.tables
    return TableOptions(
        line_tolerance=tables.line_tolerance,
        word_gap=tables.word_gap,
        reference_headers=tables.reference_headers,
        year_pattern=tables.year_pattern,
    )


def running_text_boxes(blocks: Sequence[TextBlock], profile: Profile) -> list[BBox]:
    """Return the blocks that are certainly running text, not cells of a table."""
    tables = profile.tables
    boxes = []
    for block in blocks:
        span = first_span(block)
        if (
            span is not None
            and span.font.startswith(tuple(tables.text_fonts))
            and span.size >= tables.text_min_size
            and len(block.lines) >= tables.text_min_lines
        ):
            boxes.append(block.bbox)
    return boxes


def trim_detections(
    tables: Sequence[ExtractedTable], blocks: Sequence[TextBlock], profile: Profile
) -> list[ExtractedTable]:
    """Undo detections that swallowed a text column, dropping any with no cells left."""
    boxes = running_text_boxes(blocks, profile)
    trimmed = (
        trim_swallowed_column(
            table,
            boxes,
            split_x=profile.page.split_x,
            min_overlap=profile.tables.swallow_overlap,
            margin=profile.tables.keep_margin,
        )
        for table in tables
    )
    return [table for table in trimmed if table is not None]


def drop_detections_in_figures(
    tables: Sequence[ExtractedTable], figures: Sequence[BBox], profile: Profile
) -> list[ExtractedTable]:
    """Drop detections that are really part of a figure, such as the frame of a chart."""
    limit = profile.tables.swallow_overlap

    def in_figure(table: ExtractedTable) -> bool:
        box = table.bbox
        return any(intersection_area(box, figure) > limit * area(box) for figure in figures)

    return [table for table in tables if not in_figure(table)]


def clean_table(table: ExtractedTable, spans: Sequence[Span], profile: Profile) -> ExtractedTable:
    """Turn one detection into a header and rows. Tables across pages are joined afterwards."""
    options = table_options(profile)

    def is_header(span: Span) -> bool:
        role = classify(span, profile, page=table.page, context="table")
        return role == "table_header"

    table = fill_cells_from_spans(table, spans)
    table = join_header_rows(table, is_header)
    table = join_wrapped_rows(table, options)
    return merge_phantom_columns(table)
