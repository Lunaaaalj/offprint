"""Table steps, from `prototype/README.md` items 10 to 16."""

from dataclasses import replace

from offprint.cleanup import (
    TableOptions,
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
from offprint.extraction import ExtractedTable, Span, TableCell

BOX = (0.0, 0.0, 10.0, 10.0)


def cell(text: str | None, x: float = 0.0, y: float = 0.0, font: str = "body") -> TableCell | None:
    if text is None:
        return None
    if not text:
        return TableCell(spans=(), bbox=BOX)
    box = (x, y, x + 10.0, y + 8.0)
    return TableCell(spans=(Span(text=text, bbox=box, page=1, font=font),), bbox=box)


def row(*texts: str | None, y: float = 0.0, font: str = "body") -> tuple[TableCell | None, ...]:
    return tuple(cell(text, x=i * 20.0, y=y, font=font) for i, text in enumerate(texts))


def table(*rows: tuple[TableCell | None, ...], header: tuple = ()) -> ExtractedTable:
    return ExtractedTable(rows=rows, bbox=(0.0, 0.0, 100.0, 100.0), page=1, header=header)


def grid(table: ExtractedTable) -> list[list[str]]:
    return [[cell_text(c) for c in r] for r in table.rows]


def header(table: ExtractedTable) -> list[str]:
    return [cell_text(c) for c in table.header]


# Item 10: trimming a swallowed text column (Table 8, p. 13)


def swallowing_table() -> ExtractedTable:
    def box_cell(x0: float, x1: float) -> TableCell:
        return TableCell(spans=(), bbox=(x0, 0.0, x1, 20.0))

    return ExtractedTable(
        rows=((box_cell(50, 170), box_cell(170, 290), box_cell(305, 545)),),
        bbox=(50.0, 0.0, 545.0, 200.0),
        page=1,
    )


def test_a_table_over_right_hand_text_keeps_the_left_cells() -> None:
    trimmed = trim_swallowed_column(swallowing_table(), [(305, 10, 545, 190)], split_x=297.5)

    assert trimmed is not None
    assert [c is not None for c in trimmed.rows[0]] == [True, True, False]
    assert trimmed.bbox == (50, 0, 290, 200)


def test_a_table_over_left_hand_text_keeps_the_right_cells() -> None:
    trimmed = trim_swallowed_column(swallowing_table(), [(50, 10, 290, 190)], split_x=297.5)

    assert trimmed is not None
    assert [c is not None for c in trimmed.rows[0]] == [False, False, True]
    assert trimmed.bbox == (305, 0, 545, 200)


def test_a_full_width_table_without_text_under_it_stays() -> None:
    original = swallowing_table()

    assert trim_swallowed_column(original, [(50, 300, 290, 400)], split_x=297.5) is original


def test_text_mostly_outside_the_table_does_not_count() -> None:
    original = swallowing_table()

    assert trim_swallowed_column(original, [(305, 150, 545, 400)], split_x=297.5) is original


def test_a_single_column_table_stays() -> None:
    original = replace(swallowing_table(), bbox=(50.0, 0.0, 290.0, 200.0))

    assert trim_swallowed_column(original, [(50, 10, 290, 190)], split_x=297.5) is original


def test_a_table_with_nothing_left_is_dropped() -> None:
    all_in_gutter = ExtractedTable(
        rows=((TableCell(spans=(), bbox=(280, 0, 320, 10)),),), bbox=(280, 0, 320, 10), page=1
    )

    assert trim_swallowed_column(all_in_gutter, [(280, 1, 290, 9)], split_x=297.5) is None


# Item 11: building cell text from spans


def test_cells_fill_with_the_spans_inside_them() -> None:
    spans = [
        Span(text="This proposed ", bbox=(1, 1, 8, 5), page=1),
        Span(text="research", bbox=(8, 1, 9, 5), page=1),
        Span(text="elsewhere", bbox=(50, 50, 60, 60), page=1),
        Span(text="other page", bbox=(1, 1, 8, 5), page=2),
    ]
    empty = ExtractedTable(
        rows=((TableCell(spans=(), bbox=BOX), None),), bbox=(0, 0, 100, 100), page=1
    )

    filled = fill_cells_from_spans(empty, spans)

    assert cell_text(filled.rows[0][0]) == "This proposed research"
    assert filled.rows[0][1] is None


def test_a_span_straddling_a_cell_edge_goes_where_its_centre_is() -> None:
    spans = [Span(text="mostly out", bbox=(8, 1, 30, 5), page=1)]
    empty = ExtractedTable(rows=((TableCell(spans=(), bbox=BOX),),), bbox=BOX, page=1)

    assert cell_text(fill_cells_from_spans(empty, spans).rows[0][0]) == ""


def test_cell_text_reads_lines_in_order() -> None:
    first = Span(text="second", bbox=(0, 20, 10, 28), page=1)
    second = Span(text="first", bbox=(0, 0, 10, 8), page=1)

    assert cell_text(TableCell(spans=(first, second), bbox=BOX)) == "first second"


# Item 12: wrapped rows


def test_a_row_with_an_empty_first_cell_joins_the_row_above() -> None:
    joined = join_wrapped_rows(table(row("A", "one"), row("", "two", y=10), row("B", "x", y=20)))

    assert grid(joined) == [["A", "one two"], ["B", "x"]]


def test_a_row_with_a_first_cell_stays() -> None:
    original = table(row("A", "one"), row("B", ""))

    assert grid(join_wrapped_rows(original)) == [["A", "one"], ["B", ""]]


def test_blank_rows_are_dropped() -> None:
    assert grid(join_wrapped_rows(table(row("A", "x"), row("", ""), row("B", "y")))) == [
        ["A", "x"],
        ["B", "y"],
    ]


def test_a_first_row_with_an_empty_cell_has_nothing_to_join() -> None:
    assert grid(join_wrapped_rows(table(row("", "alone")))) == [["", "alone"]]


def reference_table(*rows: tuple[TableCell | None, ...]) -> ExtractedTable:
    return table(*rows, header=row("References", "Method"))


def test_a_reference_row_without_its_year_absorbs_the_next() -> None:
    joined = join_wrapped_rows(
        reference_table(
            row("Smith and", "CNN"),
            row("Jones (2021)", "too", y=10),
            row("Lee (2020a)", "SVM", y=20),
        )
    )

    assert grid(joined) == [["Smith and Jones (2021)", "CNN too"], ["Lee (2020a)", "SVM"]]


def test_a_finished_reference_row_stays() -> None:
    joined = join_wrapped_rows(reference_table(row("Lee (2020)", "SVM"), row("Kim (2019)", "CNN")))

    assert len(joined.rows) == 2


def test_the_year_rule_only_applies_to_reference_tables() -> None:
    joined = join_wrapped_rows(
        table(row("Smith and", "x"), row("Jones", "y"), header=row("Who", ""))
    )

    assert len(joined.rows) == 2


def test_reference_headers_and_year_pattern_are_options() -> None:
    options = TableOptions(reference_headers=("Study",), year_pattern=r"done$")
    joined = join_wrapped_rows(
        table(row("first", "x"), row("done", "y", y=10), header=row("Study", "Note")), options
    )

    assert grid(joined) == [["first done", "x y"]]


# Item 13: header rows


def is_header_span(span: Span) -> bool:
    return span.font == "head"


def test_consecutive_header_rows_join_column_by_column() -> None:
    joined = join_header_rows(
        table(
            row("Data", "Result", font="head"),
            row("augmentation", "", y=10, font="head"),
            row("flip", "good", y=20),
        ),
        is_header_span,
    )

    assert header(joined) == ["Data augmentation", "Result"]
    assert grid(joined) == [["flip", "good"]]


def test_a_mixed_row_is_not_a_header() -> None:
    mixed = (cell("Data", font="head"), cell("value", x=20, font="body"))

    joined = join_header_rows(table(mixed), is_header_span)

    assert joined.header == ()
    assert len(joined.rows) == 1


def test_a_header_styled_row_below_the_data_stays_a_row() -> None:
    joined = join_header_rows(
        table(
            row("Head", font="head"),
            row("data", y=10),
            row("Subsection", y=20, font="head"),
        ),
        is_header_span,
    )

    assert header(joined) == ["Head"]
    assert grid(joined) == [["data"], ["Subsection"]]


def test_a_table_without_header_styling_has_no_header() -> None:
    assert join_header_rows(table(row("a", "b")), is_header_span).header == ()


# Item 14: phantom columns (Tables 11, 19)


def test_a_phantom_column_folds_into_the_neighbour_with_fewer_conflicts() -> None:
    phantom = table(
        row("ADNI", "", "good"),
        row("", "OASIS", "fine", y=10),
        header=row("Datasets", "", "Result"),
    )

    merged = merge_phantom_columns(phantom)

    assert header(merged) == ["Datasets", "Result"]
    assert grid(merged) == [["ADNI", "good"], ["OASIS", "fine"]]


def test_a_conflict_on_the_left_sends_the_column_right() -> None:
    phantom = table(row("a", "b", ""), header=row("Left", "", "Right"))

    assert grid(merge_phantom_columns(phantom)) == [["a", "b"]]


def test_a_tie_goes_left() -> None:
    phantom = table(row("a", "b", "c"), header=row("Left", "", "Right"))

    assert grid(merge_phantom_columns(phantom)) == [["a b", "c"]]


def test_a_tie_goes_to_the_neighbour_whose_text_starts_in_the_same_place() -> None:
    # Tables 6, 10 and 17: a real column's short last lines form a phantom column inside it. These
    # lines start with the column, so they belong to it, not to the references on their left.
    reference = cell("Khan et al. (2022)", x=0.0)
    last_line = cell("and performance metrics.", x=70.0, y=30.0)
    long_lines = cell("The multimodal approach", x=70.0)
    phantom = table(
        (reference, last_line, long_lines),
        header=(cell("References"), cell(""), cell("Contributions", x=70.0)),
    )

    assert grid(merge_phantom_columns(phantom)) == [
        ["Khan et al. (2022)", "The multimodal approach and performance metrics."]
    ]


def test_a_column_emptied_by_trimming_disappears() -> None:
    trimmed = table(row("a", None), header=(cell("Only"), None))

    merged = merge_phantom_columns(trimmed)

    assert header(merged) == ["Only"]
    assert grid(merged) == [["a"]]


def test_named_columns_stay() -> None:
    original = table(row("a", "b"), header=row("One", "Two"))

    assert grid(merge_phantom_columns(original)) == [["a", "b"]]


def test_a_table_without_a_header_stays() -> None:
    original = table(row("a", "", "b"))

    assert merge_phantom_columns(original) is original


def test_a_table_of_only_empty_headers_stays() -> None:
    assert len(merge_phantom_columns(table(row("a", "b"), header=row("", ""))).header) == 2


# Item 15: tables across pages


def test_a_continued_table_appends_and_skips_the_repeated_header() -> None:
    first = table(row("a", "b"), header=row("One", "Two"))
    second = replace(table(row("c", "d"), header=row("One", "Two")), page=2)

    joined = join_continued_tables([first, second], [False, True])

    assert len(joined) == 1
    assert grid(joined[0]) == [["a", "b"], ["c", "d"]]
    assert joined[0].page == 1


def test_a_header_repeated_as_a_plain_row_is_skipped() -> None:
    first = table(row("a", "b"), header=row("One", "Two"))
    second = table(row("One", "Two"), row("c", "d"))

    joined = join_continued_tables([first, second], [False, True])

    assert grid(joined[0]) == [["a", "b"], ["c", "d"]]


def test_a_continuation_without_a_header_appends() -> None:
    first = table(row("a"), header=row("One"))

    assert grid(join_continued_tables([first, table(row("b"))], [False, True])[0]) == [["a"], ["b"]]


def test_a_different_header_on_a_continuation_keeps_its_text() -> None:
    first = table(row("a"), header=row("One"))
    second = table(row("b"), header=row("Surprise"))

    assert grid(join_continued_tables([first, second], [False, True])[0]) == [
        ["a"],
        ["Surprise"],
        ["b"],
    ]


def test_tables_not_marked_as_continued_stay_separate() -> None:
    first = table(row("a"), header=row("One"))
    second = table(row("b"), header=row("One"))

    assert len(join_continued_tables([first, second], [False, False])) == 2


def test_a_continuation_with_nothing_before_it_stands_alone() -> None:
    assert len(join_continued_tables([table(row("a"))], [True])) == 1


# Square rows


def test_short_rows_and_headers_are_padded() -> None:
    squared = square_rows(table(row("a", "b", "c"), row("d"), header=row("One", "Two")))

    assert [len(r) for r in (squared.header, *squared.rows)] == [3, 3, 3]


def test_square_tables_stay() -> None:
    original = table(row("a", "b"), header=row("One", "Two"))

    assert square_rows(original) == original


# Item 16: pairing captions with tables (p. 14)


def test_two_tables_at_the_same_y_pair_by_horizontal_overlap() -> None:
    left_caption = (49.0, 90.0, 280.0, 98.0)
    right_caption = (305.0, 90.0, 540.0, 98.0)
    tables = [(305.0, 100.0, 546.0, 300.0), (49.0, 100.0, 291.0, 300.0)]

    assert pair_captions([left_caption, right_caption], tables) == (1, 0)


def test_the_nearest_table_wins_in_one_column() -> None:
    caption = (49.0, 90.0, 280.0, 98.0)
    tables = [(49.0, 400.0, 291.0, 500.0), (49.0, 100.0, 291.0, 300.0)]

    assert pair_captions([caption], tables) == (1,)


def test_a_table_on_the_wrong_side_does_not_pair() -> None:
    caption = (49.0, 390.0, 280.0, 398.0)

    assert pair_captions([caption], [(49.0, 100.0, 291.0, 300.0)]) == (None,)


def test_a_table_in_the_other_column_does_not_pair() -> None:
    caption = (49.0, 90.0, 280.0, 98.0)

    assert pair_captions([caption], [(305.0, 100.0, 546.0, 300.0)]) == (None,)


def test_captions_below_their_tables() -> None:
    caption = (49.0, 310.0, 280.0, 318.0)
    tables = [(49.0, 100.0, 291.0, 300.0)]

    assert pair_captions([caption], tables, side="below") == (0,)
    assert pair_captions([caption], tables, side="above") == (None,)


def test_a_table_pairs_only_once() -> None:
    first = (49.0, 80.0, 280.0, 88.0)
    second = (49.0, 90.0, 280.0, 98.0)

    assert pair_captions([first, second], [(49.0, 100.0, 291.0, 300.0)]) == (0, None)
