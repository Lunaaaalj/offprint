"""`<table>` to a rectangle: spans, header rows and hostile attributes."""

from lxml import etree

from offprint.adapters.jats.tables import RawCell, expand_spans, merge_header, read_table
from offprint.ir import Bold, Text


def cell(text: str, rowspan: int = 1, colspan: int = 1) -> RawCell:
    return RawCell((Text(text),), rowspan, colspan)


def shape(rows):
    return [[runs[0].text if runs else "" for runs in row] for row in rows]


def test_a_rowspan_repeats_so_each_row_reads_alone() -> None:
    rows = [[cell("a", rowspan=2), cell("b")], [cell("c")]]

    assert shape(expand_spans(rows, repeat_columns=False)) == [["a", "b"], ["a", "c"]]


def test_a_rowspan_in_the_last_column() -> None:
    rows = [[cell("a"), cell("b", rowspan=2)], [cell("c")]]

    assert shape(expand_spans(rows, repeat_columns=False)) == [["a", "b"], ["c", "b"]]


def test_a_body_colspan_appears_once() -> None:
    rows = [[cell("group", colspan=2)], [cell("a"), cell("b")]]

    assert shape(expand_spans(rows, repeat_columns=False)) == [["group", ""], ["a", "b"]]


def test_a_header_colspan_names_every_column() -> None:
    rows = [[cell("group", colspan=2)]]

    assert shape(expand_spans(rows, repeat_columns=True)) == [["group", "group"]]


def test_a_cell_spanning_rows_and_columns() -> None:
    rows = [[cell("a", rowspan=2, colspan=2), cell("b")], [cell("c")]]

    assert shape(expand_spans(rows, repeat_columns=True)) == [["a", "a", "b"], ["a", "a", "c"]]


def test_a_rowspan_past_the_end_of_the_section_stops_there() -> None:
    assert shape(expand_spans([[cell("a", rowspan=9)]], repeat_columns=False)) == [["a"]]


def test_header_rows_fold_from_the_top() -> None:
    rows = [
        [(Text("Group"),), (Text("Group"),), ()],
        [(Text("x"),), (Text("y"),), (Text("z"),)],
    ]

    assert merge_header(rows) == (
        (Text("Group"), Text(" "), Text("x")),
        (Text("Group"), Text(" "), Text("y")),
        (Text("z"),),
    )


def test_a_header_cell_spanning_both_rows_appears_once() -> None:
    assert merge_header([[(Text("a"),)], [(Text("a"),)]]) == (((Text("a"),)),)


def table(inner: str):
    return read_table(etree.fromstring(f"<table>{inner}</table>"), [])


def test_the_fixtures_shape() -> None:
    header, rows = table(
        '<thead><tr><th rowspan="1" colspan="1">Element</th><th>Definition</th></tr></thead>'
        "<tbody><tr><td>P</td><td>Research <bold>studies</bold></td></tr></tbody>"
    )

    assert header == ((Text("Element"),), (Text("Definition"),))
    assert rows == [[(Text("P"),), (Text("Research "), Bold((Text("studies"),)))]]


def test_without_a_thead_the_first_row_is_the_header() -> None:
    header, rows = table("<tbody><tr><td>a</td></tr><tr><td>b</td></tr></tbody>")

    assert header == ((Text("a"),),)
    assert rows == [[(Text("b"),)]]


def test_rows_with_no_section() -> None:
    header, rows = table("<tr><td>a</td></tr><tr><td>b</td></tr>")

    assert (len(header), len(rows)) == (1, 1)


def test_short_rows_are_padded() -> None:
    header, rows = table(
        "<thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>c</td></tr></tbody>"
    )

    assert len(header) == 2
    assert rows == [[(Text("c"),), ()]]


def test_a_foot_row_stays_with_the_body() -> None:
    _, rows = table(
        "<thead><tr><th>a</th></tr></thead><tbody><tr><td>b</td></tr></tbody>"
        "<tfoot><tr><td>c</td></tr></tfoot>"
    )

    assert len(rows) == 2


def test_a_span_is_clamped() -> None:
    header, rows = table('<tr><td colspan="99999999">a</td></tr><tr><td rowspan="0">b</td></tr>')

    assert len(header) == 1000
    assert len(rows[0]) == 1000


def test_a_nonsense_span_counts_as_one() -> None:
    header, _ = table('<tr><td colspan="wide">a</td></tr>')

    assert len(header) == 1


def test_an_empty_table() -> None:
    assert table("") == ((), [])
