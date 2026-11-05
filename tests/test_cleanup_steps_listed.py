"""Every cleanup step is listed, so QA reports (#6) can say which ones ran."""

import offprint.cleanup as cleanup
from offprint.cleanup.registry import registered


def test_importing_the_package_fills_the_registry() -> None:
    steps = {item.name: item.stage for item in registered()}

    assert steps == {
        "strip_control_characters": "text",
        "expand_ligatures": "text",
        "fix_combining_marks": "text",
        "collapse_whitespace": "text",
        "dehyphenate": "text",
        "separate_words": "text",
        "spans_to_runs": "text",
        "regroup_lines": "caption",
        "merge_touching_blocks": "caption",
        "join_paragraphs": "paragraph",
        "trim_swallowed_column": "table",
        "fill_cells_from_spans": "table",
        "join_header_rows": "table",
        "join_wrapped_rows": "table",
        "merge_phantom_columns": "table",
        "join_continued_tables": "table",
        "square_rows": "table",
        "pair_captions": "table",
    }


def test_each_listed_step_is_exported() -> None:
    for item in registered():
        assert getattr(cleanup, item.name) is item.function
