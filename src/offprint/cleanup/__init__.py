"""Cleanup steps: pure functions on IR or extraction data, each with its own unit test (#4).

Importing this package fills the registry, so `registered()` lists every step.
"""

from offprint.cleanup.captions import CaptionOptions, merge_touching_blocks, regroup_lines
from offprint.cleanup.paragraphs import ParagraphOptions, join_paragraphs
from offprint.cleanup.registry import CleanupStep, registered, step
from offprint.cleanup.runs import join_runs, plain_text
from offprint.cleanup.tables import (
    TableOptions,
    cell_lines,
    cell_text,
    fill_cells_from_spans,
    join_continued_tables,
    join_header_rows,
    join_wrapped_rows,
    merge_phantom_columns,
    pair_captions,
    square_rows,
    trim_swallowed_column,
)
from offprint.cleanup.text import (
    TextOptions,
    clean_text,
    collapse_whitespace,
    dehyphenate,
    expand_ligatures,
    fix_combining_marks,
    keep_hyphen_from_vocabulary,
    separate_words,
    spans_to_runs,
    strip_control_characters,
    vocabulary,
)

__all__ = [
    "CaptionOptions",
    "CleanupStep",
    "ParagraphOptions",
    "TableOptions",
    "TextOptions",
    "cell_lines",
    "cell_text",
    "clean_text",
    "collapse_whitespace",
    "dehyphenate",
    "expand_ligatures",
    "fill_cells_from_spans",
    "fix_combining_marks",
    "join_continued_tables",
    "join_header_rows",
    "join_paragraphs",
    "join_runs",
    "join_wrapped_rows",
    "keep_hyphen_from_vocabulary",
    "merge_phantom_columns",
    "merge_touching_blocks",
    "pair_captions",
    "plain_text",
    "regroup_lines",
    "registered",
    "separate_words",
    "spans_to_runs",
    "square_rows",
    "step",
    "strip_control_characters",
    "trim_swallowed_column",
    "vocabulary",
]
