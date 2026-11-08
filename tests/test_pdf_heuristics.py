"""Template heuristics of the PDF adapter, from minimal `prototype/README.md` reproductions."""

from dataclasses import dataclass, replace

import pytest

from offprint.adapters.pdf.assemble import (
    Crop,
    LayoutError,
    TableElement,
    TextElement,
    assemble,
    byline_block,
    document_vocabulary,
    join_tables,
    merge_caption_fragments,
    page_elements,
    read_caption,
)
from offprint.adapters.pdf.equations import (
    EquationPiece,
    group_equations,
    is_display_equation,
)
from offprint.adapters.pdf.extract import PageData
from offprint.adapters.pdf.figures import figure_region, include_labels
from offprint.adapters.pdf.layout import column_of, reading_order
from offprint.adapters.pdf.metadata import (
    BylineBlock,
    FrontMatter,
    build_meta,
    parse_keywords,
    read_authors,
    read_stamps,
)
from offprint.adapters.pdf.roles import block_role
from offprint.adapters.pdf.tables import (
    clean_table,
    drop_detections_in_figures,
    running_text_boxes,
)
from offprint.cleanup import cell_text, plain_text
from offprint.cleanup.geometry import union
from offprint.extraction import ExtractedTable, Line, Span, TableCell, TextBlock
from offprint.ir import (
    Asset,
    BBox,
    Equation,
    Figure,
    Heading,
    Italic,
    ListItem,
    Paragraph,
    Problem,
    Reference,
    Table,
    Text,
)
from offprint.profiles import load_profile
from offprint.profiles.schema import LabelRules

PROFILE = load_profile("frontiers")
LAYOUT = PROFILE.page
BODY = "MinionPro-Regular"
SANS = "MuseoSans-500"
LABEL = "MuseoSans-700"
CAPTION = "MuseoSans-300"
ITALIC = "MinionPro-It"


def text_block(
    text: str,
    box: BBox = (49.0, 100.0, 291.0, 110.0),
    *,
    font: str = BODY,
    size: float = 9.0,
    page: int = 2,
    lines: int = 1,
) -> TextBlock:
    span = Span(text=text, bbox=box, page=page, font=font, size=size)
    return TextBlock(
        lines=tuple(Line(spans=(span,), bbox=box) for _ in range(lines)), bbox=box, page=page
    )


def page_data(*blocks: TextBlock, number: int = 2, **fields: object) -> PageData:
    values: dict = {"tables": (), "graphics": (), "figure_alts": ()}
    return PageData(number=number, width=595.0, height=842.0, blocks=blocks, **{**values, **fields})


def fake_crop(*, page: int, bbox: BBox, zoom: float, grayscale: bool, asset_id: str) -> Asset:
    return Asset(id=asset_id, mime="image/png", bytes=b"png", width=1, height=1)


CROP: Crop = fake_crop


def build(*pages: PageData):
    return assemble(pages, PROFILE, crop=CROP, pdf_metadata={"title": "From the PDF"})


def runs_of(doc) -> list[str]:
    return [plain_text(b.runs) for b in doc.blocks if hasattr(b, "runs")]


# Item 5: two columns plus full-width items


@dataclass
class Item:
    name: str
    column: str
    top: float
    bottom: float


def test_a_page_reads_left_column_then_right() -> None:
    items = [Item("r", "right", 100, 200), Item("l", "left", 300, 400)]

    assert [i.name for i in reading_order(items)] == ["l", "r"]


def test_a_full_width_element_cuts_the_page_into_bands() -> None:
    items = [
        Item("left below", "left", 500, 600),
        Item("right above", "right", 100, 200),
        Item("wide", "full", 300, 400),
        Item("right below", "right", 500, 600),
        Item("left above", "left", 150, 250),
    ]

    assert [i.name for i in reading_order(items)] == [
        "left above",
        "right above",
        "wide",
        "left below",
        "right below",
    ]


def test_a_box_across_the_gutter_is_full_width() -> None:
    assert column_of((49, 0, 546, 10), LAYOUT) == "full"
    assert column_of((49, 0, 291, 10), LAYOUT) == "left"
    assert column_of((305, 0, 546, 10), LAYOUT) == "right"


def test_a_box_only_just_over_the_gutter_stays_in_its_column() -> None:
    assert column_of((49, 0, 310, 10), LAYOUT) == "left"


# Item 7: running header, footer and the first-page sidebar


def test_running_header_and_footer_are_dropped() -> None:
    page = page_data(
        text_block("Header", (49, 20, 300, 30)),
        text_block("Body text.", (49, 100, 291, 110)),
        text_block("Footer", (49, 801, 546, 808)),
    )

    assert runs_of(build(page)) == ["Body text."]


def test_the_sidebar_keeps_only_citation_and_copyright() -> None:
    page = page_data(
        text_block("EDITED BY Someone", (49, 190, 135, 226), font=LABEL, size=5.5, page=1),
        text_block("CITATION Nibila Y", (49, 363, 177, 422), font=LABEL, size=5.5, page=1),
        text_block("Main text.", (220, 300, 545, 320), page=1),
        number=1,
    )

    doc = build(page)

    assert runs_of(doc) == ["Main text.", "CITATION Nibila Y"]
    assert [b.role for b in doc.blocks] == ["body", "meta"]


def test_the_sidebar_is_only_on_its_own_page() -> None:
    page = page_data(text_block("Narrow text.", (49, 100, 150, 110)))

    assert runs_of(build(page)) == ["Narrow text."]


# Roles


@pytest.mark.parametrize(
    ("font", "size", "page", "role"),
    [
        (SANS, 20.92, 1, "title"),
        (SANS, 13.45, 2, "h1"),
        (SANS, 11.96, 2, "h2"),
        (SANS, 10.46, 2, "h3"),
        (SANS, 8.97, 2, "h3"),
        (SANS, 10.96, 1, "authors"),
        (CAPTION, 6.97, 1, "affiliation"),
        (CAPTION, 8.97, 1, "abstract"),
        (BODY, 9.0, 2, "body"),
        (BODY, 6.97, 2, "small"),
        ("Calibri", 6.4, 2, "ignore"),
        ("Calibri-Bold", 9.0, 1, "ignore"),
        (LABEL, 5.5, 1, "ignore"),
    ],
)
def test_font_and_size_decide_the_role(font: str, size: float, page: int, role: str) -> None:
    assert block_role(text_block("x", font=font, size=size, page=page), PROFILE) == role


def test_text_rules_win_over_size() -> None:
    block = text_block("KEYWORDS deep learning", font=LABEL, size=5.5, page=1)

    assert block_role(block, PROFILE) == "keywords"


def test_a_stray_continued_marker_is_ignored() -> None:
    assert block_role(text_block("(Continued)", size=7.0), PROFILE) == "ignore"


def test_chart_labels_do_not_become_paragraphs() -> None:
    page = page_data(text_block("Accuracy", font="Calibri", size=6.4))

    assert build(page).blocks == ()


# Item 8: captions in pieces


def test_touching_caption_fragments_merge_and_parse() -> None:
    blocks = [
        text_block("hical summary", (121, 100, 200, 108), font=CAPTION, size=6.97),
        text_block("FIGU", (50, 100, 70, 108), font=LABEL, size=5.5),
        text_block("RE 16 ", (70, 100, 100, 108), font=LABEL, size=5.5),
        text_block("Grap", (101, 100, 120, 108), font=CAPTION, size=6.97),
        text_block("Running text stays out.", (49, 200, 291, 210)),
    ]

    merged = merge_caption_fragments(blocks, PROFILE)
    captions = [c for c in (read_caption(b, PROFILE) for b in merged) if c]

    assert len(merged) == 2
    assert [(c.kind, c.number, plain_text(c.runs)) for c in captions] == [
        ("figure", "16", "Graphical summary")
    ]


def test_a_spaced_out_label_still_parses() -> None:
    caption = read_caption(text_block("F I G U R E 3 A figure", font=LABEL, size=5.5), PROFILE)

    assert caption is not None
    assert (caption.kind, caption.number) == ("figure", "3")


def test_a_caption_keeps_its_styling_after_the_label() -> None:
    label = Span(text="TABLE 2 ", bbox=(49, 0, 80, 8), page=2, font=LABEL, size=5.5)
    plain = Span(text="Scores on ", bbox=(80, 0, 120, 8), page=2, font=CAPTION, size=6.97)
    styled = Span(
        text="ADNI",
        bbox=(120, 0, 140, 8),
        page=2,
        font="MuseoSans-300Italic",
        size=6.97,
        italic=True,
    )
    box = (49.0, 0.0, 140.0, 8.0)
    block = TextBlock(lines=(Line(spans=(label, plain, styled), bbox=box),), bbox=box, page=2)

    caption = read_caption(block, PROFILE)

    assert caption is not None
    assert caption.runs == (Text("Scores on "), Italic((Text("ADNI"),)))


def test_spans_in_other_fonts_are_not_caption_text() -> None:
    label = Span(text="FIGURE 1 ", bbox=(49, 0, 80, 8), page=2, font=LABEL, size=5.5)
    stray = Span(text="Accuracy", bbox=(80, 0, 120, 8), page=2, font="Calibri", size=6.4)
    box = (49.0, 0.0, 120.0, 8.0)
    block = TextBlock(lines=(Line(spans=(label, stray), bbox=box),), bbox=box, page=2)

    caption = read_caption(block, PROFILE)

    assert caption is not None
    assert plain_text(caption.runs) == ""


def test_ordinary_text_is_not_a_caption() -> None:
    assert read_caption(text_block("Figure 3 shows the results.", font=CAPTION), PROFILE) is None


# Item 9: figure regions


def region(caption: BBox, **fields):
    values: dict = {"blocks": [], "captions": [], "graphics": [], "page_width": 595.0}
    return figure_region(caption, profile=PROFILE, **{**values, **fields})


def test_a_figure_stops_at_the_nearest_block_above() -> None:
    found = region(
        (49, 400, 291, 410),
        blocks=[(49, 100, 291, 200), (49, 60, 291, 80)],
        graphics=[(60, 40, 280, 90), (60, 210, 280, 390)],
    )

    assert found.bbox == (58, 208, 282, 392)
    assert found.column == "left"


def test_a_figure_stops_at_a_caption_above() -> None:
    # Without this, Fig. 2 swallowed Fig. 1, and Fig. 5 swallowed Fig. 4.
    found = region(
        (49, 400, 291, 410),
        captions=[(49, 200, 291, 208)],
        graphics=[(60, 100, 280, 195), (60, 215, 280, 390)],
    )

    assert found.bbox == (58, 213, 282, 392)


def test_a_caption_in_the_other_column_does_not_bound_a_figure() -> None:
    found = region(
        (49, 400, 291, 410),
        captions=[(305, 200, 546, 208)],
        graphics=[(60, 100, 280, 390)],
    )

    assert found.bbox[1] == 98


def test_a_shape_across_the_gutter_makes_the_figure_full_width() -> None:
    found = region(
        (49, 400, 291, 410),
        blocks=[(305, 200, 546, 300)],
        graphics=[(60, 310, 540, 390)],
    )

    assert found.column == "full"
    assert found.bbox == (58, 308, 542, 392)


def test_a_narrow_figure_in_one_column_stays_there() -> None:
    assert region((305, 400, 546, 410), graphics=[(320, 100, 540, 390)]).column == "right"


def test_tiny_shapes_and_page_backgrounds_do_not_count() -> None:
    found = region(
        (49, 400, 291, 410),
        graphics=[(0, 60, 595, 390), (60, 100, 62, 390), (60, 200, 280, 300)],
    )

    assert found.bbox == (58, 198, 282, 302)


def test_a_figure_without_shapes_falls_back_to_the_column() -> None:
    found = region((49, 400, 291, 410), blocks=[(49, 100, 291, 200)])

    assert found.bbox == (49, 204, 291, 398)


# Tables


def cell(x0: float, x1: float, y0: float, y1: float) -> TableCell:
    return TableCell(spans=(), bbox=(x0, y0, x1, y1))


def span_in(text: str, box: BBox, font: str = SANS, size: float = 6.97) -> Span:
    return Span(text=text, bbox=box, page=2, font=font, size=size)


def two_row_table() -> ExtractedTable:
    return ExtractedTable(
        rows=(
            (cell(50, 100, 100, 110), cell(100, 150, 100, 110)),
            (cell(50, 100, 110, 120), cell(100, 150, 110, 120)),
        ),
        bbox=(50.0, 100.0, 150.0, 120.0),
        page=2,
    )


def test_a_row_in_header_fonts_becomes_the_header() -> None:
    # Item 13: a row is a header when all its spans use the header font.
    spans = [
        span_in("Model", (51, 101, 90, 109)),
        span_in("Score", (101, 101, 140, 109)),
        span_in("SVM", (51, 111, 90, 119), font=BODY),
        span_in("0.9", (101, 111, 140, 119), font=BODY),
    ]

    table = clean_table(two_row_table(), spans, PROFILE)

    assert [cell_text(c) for c in table.header] == ["Model", "Score"]
    assert [[cell_text(c) for c in row] for row in table.rows] == [["SVM", "0.9"]]


def test_only_multi_line_running_text_shows_a_swallowed_column() -> None:
    # Item 10: at least 3 lines of 9 pt text.
    running = text_block("text", (305, 0, 546, 100), lines=3)
    short = text_block("text", (305, 0, 546, 100), lines=2)
    small = text_block("text", (305, 0, 546, 100), lines=3, size=6.97)
    sans = text_block("text", (305, 0, 546, 100), lines=3, font=SANS)

    assert running_text_boxes([running, short, small, sans], PROFILE) == [running.bbox]


def test_a_table_detected_inside_a_figure_is_dropped() -> None:
    frame = ExtractedTable(rows=(), bbox=(60, 100, 280, 300), page=2)
    real = ExtractedTable(rows=(), bbox=(60, 400, 280, 500), page=2)

    kept = drop_detections_in_figures([frame, real], [(50, 90, 290, 310)], PROFILE)

    assert kept == [real]


def table_page(
    number: int, caption: str | None, *rows: tuple[str, str], top: float = 200
) -> PageData:
    """A page with a detected table of one-line rows, the first row in the header font."""
    cells: list = []
    spans: list[TextBlock] = []
    for index, row in enumerate(rows):
        y0 = top + index * 10
        font = SANS if index == 0 else BODY
        cells.append(tuple(cell(50 + i * 100, 150 + i * 100, y0, y0 + 10) for i in range(2)))
        for i, text in enumerate(row):
            box = (51.0 + i * 100, y0 + 1, 140.0 + i * 100, y0 + 9)
            spans.append(text_block(text, box, font=font, size=6.97, page=number))
    bottom = top + len(rows) * 10
    table = ExtractedTable(rows=tuple(cells), bbox=(50, top, 250, bottom), page=number)
    label = []
    if caption is not None:
        label = [
            text_block(caption, (50, top - 12, 250, top - 4), font=LABEL, size=5.5, page=number)
        ]
    return page_data(*label, *spans, number=number, tables=(table,))


def test_a_captioned_table_is_emitted_with_its_cells() -> None:
    doc = build(table_page(2, "TABLE 1 Scores", ("Model", "Score"), ("SVM", "0.9")))

    table = doc.blocks[0]

    assert isinstance(table, Table)
    assert table.number == "1"
    assert plain_text(table.caption) == "Scores"
    assert [plain_text(c) for c in table.header] == ["Model", "Score"]
    assert [[plain_text(c) for c in row] for row in table.rows] == [["SVM", "0.9"]]


def test_a_continued_caption_appends_and_skips_the_repeated_header() -> None:
    # Item 15.
    doc = build(
        table_page(2, "TABLE 1 Scores", ("Model", "Score"), ("SVM", "0.9")),
        table_page(3, "TABLE 1 (Continued)", ("Model", "Score"), ("CNN", "0.8")),
    )

    assert len(doc.blocks) == 1
    table = doc.blocks[0]
    assert isinstance(table, Table)
    assert [plain_text(row[0]) for row in table.rows] == ["SVM", "CNN"]
    assert plain_text(table.caption) == "Scores"


def test_a_table_with_no_caption_continues_the_open_table() -> None:
    doc = build(
        table_page(2, "TABLE 1 Scores", ("Model", "Score"), ("SVM", "0.9")),
        table_page(3, None, ("Model", "Score"), ("CNN", "0.8")),
    )

    assert sum(isinstance(block, Table) for block in doc.blocks) == 1


def test_a_new_caption_starts_a_new_table() -> None:
    doc = build(
        table_page(2, "TABLE 1 One", ("A", "B"), ("a", "b")),
        table_page(3, "TABLE 2 Two", ("C", "D"), ("c", "d")),
    )

    assert [block.number for block in doc.blocks if isinstance(block, Table)] == ["1", "2"]


def test_a_table_with_nothing_to_continue_is_an_error() -> None:
    with pytest.raises(LayoutError, match="page 2"):
        build(table_page(2, None, ("Model", "Score"), ("SVM", "0.9")))


def test_a_caption_with_no_table_is_an_error() -> None:
    label = text_block("TABLE 7 Lost", (50, 100, 250, 108), font=LABEL, size=5.5)

    with pytest.raises(LayoutError, match="caption 7"):
        build(page_data(label))


def test_text_under_a_table_is_not_a_paragraph() -> None:
    doc = build(table_page(2, "TABLE 1 Scores", ("Model", "Score"), ("SVM", "0.9")))

    assert not any(isinstance(block, Paragraph) for block in doc.blocks)


def test_joined_tables_drop_the_later_pieces_from_the_stream() -> None:
    elements = [
        *page_elements(table_page(2, "TABLE 1 S", ("M", "S"), ("a", "b")), PROFILE),
        *page_elements(table_page(3, None, ("M", "S"), ("c", "d")), PROFILE),
    ]

    joined = join_tables(elements, PROFILE)

    assert sum(isinstance(e, TableElement) for e in joined) == 1


# Item 17: display equations


def in_column(text: str, box: BBox, **fields) -> bool:
    return is_display_equation(text_block(text, box, **fields), "left", PROFILE)


def test_a_line_ending_in_a_number_at_the_edge_is_an_equation() -> None:
    assert in_column("Y = aX + b (1)", (100, 100, 290, 110))


def test_a_lone_number_span_is_an_equation_piece() -> None:
    assert in_column("(7)", (270, 100, 290, 110))


def test_a_math_font_marks_an_equation() -> None:
    assert in_column("∑", (100, 100, 120, 110), font="MTEX")


def test_a_short_centred_block_with_an_equals_sign_is_an_equation() -> None:
    assert in_column("Accuracy = TP", (100, 100, 200, 110))


def test_a_run_in_heading_without_equals_is_not_an_equation() -> None:
    # "Regression Models:" was picked up before the `=` rule.
    assert not in_column("Regression Models:", (100, 100, 200, 110))


def test_a_citation_number_inside_running_text_is_not_an_equation() -> None:
    assert not in_column("as in the earlier study (12) of", (49, 100, 200, 110))


def test_a_full_width_paragraph_with_equals_is_not_an_equation() -> None:
    assert not in_column("We found that n = 12 in all.", (49, 100, 290, 110))


def test_a_centred_bullet_is_not_an_equation() -> None:
    assert not in_column("• x = 1", (100, 100, 200, 110))


def test_small_centred_text_is_not_an_equation() -> None:
    assert not in_column("x = 1", (100, 100, 200, 110), size=6.0)


def piece(text: str, box: BBox, column: str = "left") -> EquationPiece:
    return EquationPiece(block=text_block(text, box), column=column)


def test_pieces_close_together_form_one_equation() -> None:
    # Fractions and sums come in several blocks.
    equations = group_equations(
        [piece("TP", (100, 100, 120, 108)), piece("Recall =", (60, 112, 100, 120))], PROFILE
    )

    assert len(equations) == 1
    assert equations[0].alt == "TP Recall ="
    assert equations[0].bbox == (49, 97, 291, 123)


def test_pieces_far_apart_are_two_equations() -> None:
    equations = group_equations(
        [piece("a (1)", (100, 100, 290, 108)), piece("b (2)", (100, 200, 290, 208))], PROFILE
    )

    assert [e.number for e in equations] == ["1", "2"]


def test_pieces_in_different_columns_are_two_equations() -> None:
    equations = group_equations(
        [piece("a", (100, 100, 290, 108)), piece("b", (320, 100, 540, 108), "right")], PROFILE
    )

    assert len(equations) == 2


def test_the_number_comes_out_of_the_alt() -> None:
    equation = group_equations([piece("Y = aX + b (1)", (100, 100, 290, 108))], PROFILE)[0]

    assert (equation.alt, equation.number) == ("Y = aX + b", "1")


def test_a_number_in_its_own_span_comes_out_of_the_alt() -> None:
    box = (100.0, 100.0, 290.0, 108.0)
    spans = (
        Span(text="(4)", bbox=box, page=2, font=BODY, size=9.0),
        Span(text="d(x) =", bbox=box, page=2, font=BODY, size=9.0),
    )
    block = TextBlock(lines=(Line(spans=spans, bbox=box),), bbox=box, page=2)

    equation = group_equations([EquationPiece(block=block, column="left")], PROFILE)[0]

    assert (equation.alt, equation.number) == ("d(x) =", "4")


def test_an_equation_without_a_number_has_none() -> None:
    equation = group_equations([piece("x = 1", (100, 100, 200, 108))], PROFILE)[0]

    assert equation.number is None


def test_an_equation_is_cropped_grayscale_at_the_profile_zoom() -> None:
    calls = []

    def recording_crop(**fields) -> Asset:
        calls.append(fields)
        return fake_crop(**fields)

    page = page_data(text_block("Y = aX + b (1)", (100, 100, 290, 110)))

    doc = assemble([page], PROFILE, crop=recording_crop, pdf_metadata={})

    assert isinstance(doc.blocks[0], Equation)
    assert doc.blocks[0].asset in doc.assets
    assert (calls[0]["zoom"], calls[0]["grayscale"]) == (5, True)


def test_a_figure_is_cropped_in_colour() -> None:
    calls = []

    def recording_crop(**fields) -> Asset:
        calls.append(fields)
        return fake_crop(**fields)

    page = page_data(
        text_block("FIGURE 1 A chart.", (49, 400, 291, 408), font=LABEL, size=5.5),
        graphics=((60.0, 100.0, 280.0, 390.0),),
        figure_alts=("A bar chart.",),
    )

    doc = assemble([page], PROFILE, crop=recording_crop, pdf_metadata={})

    figure = doc.blocks[0]
    assert isinstance(figure, Figure)
    assert (figure.number, figure.alt) == ("1", "A bar chart.")
    assert (calls[0]["zoom"], calls[0]["grayscale"]) == (4, False)


def test_alt_text_is_not_guessed_when_the_counts_differ() -> None:
    page = page_data(
        text_block("FIGURE 1 A chart.", (49, 400, 291, 408), font=LABEL, size=5.5),
        figure_alts=("One", "Two"),
    )

    figure = build(page).blocks[0]

    assert isinstance(figure, Figure)
    assert figure.alt is None


# Headings, lists, references and paragraphs in the stream


def test_a_heading_number_moves_out_of_the_runs() -> None:
    doc = build(page_data(text_block("2.1 Methods", font=SANS, size=11.96)))

    heading = doc.blocks[0]
    assert isinstance(heading, Heading)
    assert (heading.number, heading.level, plain_text(heading.runs)) == ("2.1", 2, "Methods")


def test_an_unnumbered_heading_keeps_its_text() -> None:
    heading = build(page_data(text_block("Funding", font=SANS, size=13.45))).blocks[0]

    assert isinstance(heading, Heading)
    assert (heading.number, heading.level, plain_text(heading.runs)) == (None, 1, "Funding")


def test_a_paragraph_continues_across_columns() -> None:
    page = page_data(
        text_block("The results of", (49, 700, 291, 710)),
        text_block("Smith were clear.", (305, 60, 546, 70)),
    )

    assert runs_of(build(page)) == ["The results of Smith were clear."]


def test_a_bullet_becomes_a_list_item_without_its_marker() -> None:
    page = page_data(
        text_block("The items are", (49, 100, 291, 110)),
        text_block("• the first", (49, 120, 291, 130)),
        text_block("continues here.", (49, 140, 291, 150)),
    )

    doc = build(page)

    assert isinstance(doc.blocks[1], ListItem)
    assert plain_text(doc.blocks[1].runs) == "the first continues here."


def test_paragraphs_under_references_become_references() -> None:
    page = page_data(
        text_block("Discussion", (49, 90, 291, 100), font=SANS, size=13.45),
        text_block("Small credits here.", (49, 110, 291, 120), size=6.97),
        text_block("References", (49, 130, 291, 140), font=SANS, size=13.45),
        text_block(
            "Smith, J. (2020). A title. J. Med. 1:2. doi: 10.1000/xyz.1.",
            (49, 150, 291, 160),
            size=6.97,
        ),
        text_block("Jones, K. (2021). Another", (49, 170, 291, 180), size=6.97),
    )

    doc = build(page)

    assert isinstance(doc.blocks[1], Paragraph)
    references = [block for block in doc.blocks if isinstance(block, Reference)]
    assert [r.doi for r in references] == ["10.1000/xyz.1", None]


def test_every_block_has_provenance_pointing_at_the_source() -> None:
    doc = build(page_data(text_block("Body.", (49, 100, 291, 110))))

    assert doc.provenance[doc.blocks[0].id].page == 2
    assert doc.provenance[doc.blocks[0].id].bbox == (49, 100, 291, 110)
    assert doc.provenance[doc.blocks[0].id].adapter == "pdf"


def test_the_keep_rule_keeps_every_line_end_hyphen() -> None:
    # On the fixture this is what saves "magnetization-prepared".
    span = Span(text="magnetization-", bbox=(0, 0, 9, 9), page=2, font=BODY, size=9.0)
    next_line = replace(span, text="prepared rapid.", bbox=(0, 10, 9, 19))
    block = TextBlock(
        lines=(
            Line(spans=(span,), bbox=span.bbox),
            Line(spans=(next_line,), bbox=next_line.bbox),
        ),
        bbox=(49, 100, 291, 120),
        page=2,
    )

    assert runs_of(build(page_data(block))) == ["magnetization-prepared rapid."]


def test_the_vocabulary_rule_leaves_out_the_pieces_of_broken_words() -> None:
    first = Span(text="the for-", bbox=(0, 0, 9, 9), page=2)
    second = replace(first, text="mation of words", bbox=(0, 10, 9, 19))
    box = (0.0, 0.0, 9.0, 19.0)
    block = TextBlock(
        lines=(Line(spans=(first,), bbox=first.bbox), Line(spans=(second,), bbox=second.bbox)),
        bbox=box,
        page=2,
    )

    assert document_vocabulary([page_data(block)]) == {"the", "of", "words"}


# Metadata


def named(text: str, box: BBox = (49, 100, 291, 110), affiliation: str = "") -> BylineBlock:
    return BylineBlock(names=text, affiliation=affiliation, bbox=box)


def affiliated(text: str, box: BBox) -> BylineBlock:
    return BylineBlock(names="", affiliation=text, bbox=box)


def summary(authors) -> list[tuple]:
    return [(a.name, a.affiliations, a.corresponding, a.markers) for a in authors]


def test_authors_split_and_the_marker_shows_who_corresponds() -> None:
    byline = [
        named("Y. Nibila and M. Sivagami*", (49, 100, 291, 110)),
        affiliated("Vellore", (49, 120, 291, 128)),
    ]

    assert summary(read_authors(byline, PROFILE)) == [
        ("Y. Nibila", ("Vellore",), False, ()),
        ("M. Sivagami", ("Vellore",), True, ()),
    ]


GRID = replace(
    PROFILE, metadata=replace(PROFILE.metadata, author_markers="∗†‡", author_separator="$^")
)


def test_a_grid_of_four_authors_each_with_their_own_affiliation() -> None:
    byline = [
        named("Ashish Vaswani∗", (133, 234, 204, 245), "Google Brain"),
        named("Noam Shazeer∗", (239, 234, 305, 245), "Google Brain"),
        named("Niki Parmar∗", (324, 234, 407, 267), "Google Research"),
        named("Aidan N. Gomez∗†", (422, 234, 497, 267), "University of Toronto"),
    ]

    assert summary(read_authors(byline, GRID)) == [
        ("Ashish Vaswani", ("Google Brain",), False, ("∗",)),
        ("Noam Shazeer", ("Google Brain",), False, ("∗",)),
        ("Niki Parmar", ("Google Research",), False, ("∗",)),
        ("Aidan N. Gomez", ("University of Toronto",), False, ("∗", "†")),
    ]


def test_an_affiliation_block_belongs_to_the_name_block_just_above_it() -> None:
    byline = [
        named("Ashish Vaswani∗", (133, 234, 204, 245)),
        named("Noam Shazeer∗", (239, 234, 305, 245)),
        named("Łukasz Kaiser∗", (394, 284, 460, 295)),
        affiliated("Google Brain", (117, 246, 216, 267)),
        affiliated("Google Brain B", (231, 246, 309, 267)),
        affiliated("Google Lukasz", (365, 296, 485, 317)),
    ]

    assert [(a.name, a.affiliations) for a in read_authors(byline, GRID)] == [
        ("Ashish Vaswani", ("Google Brain",)),
        ("Noam Shazeer", ("Google Brain B",)),
        ("Łukasz Kaiser", ("Google Lukasz",)),
    ]


def test_several_affiliation_blocks_under_one_byline_all_belong_to_it() -> None:
    byline = [
        named("A and B", (49, 100, 291, 110)),
        affiliated("Lab X", (49, 120, 291, 128)),
        affiliated("Lab Y", (49, 130, 291, 138)),
    ]

    assert [a.affiliations for a in read_authors(byline, PROFILE)] == [("Lab X", "Lab Y")] * 2


def test_an_affiliation_with_no_name_above_it_goes_to_the_authors_without_one() -> None:
    byline = [
        affiliated("Lab X", (49, 50, 291, 58)),
        named("A", (49, 100, 291, 110), "Lab A"),
        named("B", (300, 100, 500, 110)),
    ]

    assert [(a.name, a.affiliations) for a in read_authors(byline, PROFILE)] == [
        ("A", ("Lab A",)),
        ("B", ("Lab X",)),
    ]


def test_the_corresponding_marker_does_not_become_a_note_marker() -> None:
    assert summary(read_authors([named("M. Sivagami*")], PROFILE)) == [
        ("M. Sivagami", (), True, ())
    ]


def test_a_byline_with_no_names_gives_no_authors() -> None:
    assert read_authors([], PROFILE) == ()
    assert read_authors([affiliated("Lab X", (0, 0, 1, 1))], PROFILE) == ()


# The lines of one byline block

EMAILS = replace(GRID, metadata=replace(GRID.metadata, email=r"\S+@\S+\.\w+"))


def line_of(text: str, font: str, size: float, top: float, page: int = 2) -> Line:
    box = (49.0, top, 200.0, top + size)
    return Line(spans=(Span(text=text, bbox=box, page=page, font=font, size=size),), bbox=box)


def block_of(*lines: Line, page: int = 2) -> TextBlock:
    return TextBlock(lines=lines, bbox=union(line.bbox for line in lines), page=page)


MONO = "SFTT1000"


def test_a_block_splits_into_name_affiliation_and_email_by_style() -> None:
    block = block_of(
        line_of("Niki Parmar∗", SANS, 10.0, 234),
        line_of("Google Research", BODY, 10.0, 246),
        line_of("nikip@google.com", MONO, 10.0, 258),
    )

    found = byline_block(block, "authors", EMAILS, None)

    assert (found.names, found.affiliation) == ("Niki Parmar∗", "Google Research")
    assert found.bbox == block.bbox


def test_names_that_wrap_onto_a_second_line_stay_names() -> None:
    block = block_of(
        line_of("Y. Nibila, M. Sivagami, A. Longname,", SANS, 10.0, 100),
        line_of("B. Another and C. Last", SANS, 10.0, 112),
    )

    found = byline_block(block, "authors", PROFILE, None)

    assert found.names == "Y. Nibila, M. Sivagami, A. Longname, B. Another and C. Last"
    assert found.affiliation == ""


def test_an_affiliation_block_has_no_names() -> None:
    block = block_of(
        line_of("Google Brain", BODY, 10.0, 246), line_of("avaswani@google.com", MONO, 10.0, 258)
    )

    found = byline_block(block, "affiliation", EMAILS, None)

    assert (found.names, found.affiliation) == ("", "Google Brain")


def test_without_an_email_rule_nothing_is_dropped_as_an_email() -> None:
    block = block_of(line_of("Google Brain", BODY, 10.0, 246), line_of("a@b.com", MONO, 10.0, 258))

    assert byline_block(block, "affiliation", GRID, None).affiliation == "Google Brain a@b.com"


def test_a_grid_through_the_whole_adapter() -> None:
    def author(left: float, name: str, affiliation: str, email: str) -> TextBlock:
        return block_of(
            *(
                replace(line, bbox=(left, line.bbox[1], left + 90, line.bbox[3]))
                for line in (
                    line_of(name, SANS, 10.7, 234, page=1),
                    line_of(affiliation, "MuseoSans-300", 7.0, 247, page=1),
                    line_of(email, MONO, 7.0, 256, page=1),
                )
            ),
            page=1,
        )

    page = page_data(
        author(115, "Ada One∗", "Lab X", "a@x.org"),
        author(205, "Ben Two†", "Lab X", "b@x.org"),
        author(310, "Cy Three", "Lab Y", "c@y.org"),
        author(410, "Di Four", "Lab Z", "d@z.org"),
        number=1,
    )

    doc = assemble([page], EMAILS, crop=CROP, pdf_metadata={})

    assert summary(doc.meta.authors) == [
        ("Ada One", ("Lab X",), False, ("∗",)),
        ("Ben Two", ("Lab X",), False, ("†",)),
        ("Cy Three", ("Lab Y",), False, ()),
        ("Di Four", ("Lab Z",), False, ()),
    ]


# The arXiv stamp and the venue line

STAMPS = replace(
    PROFILE,
    metadata=replace(
        PROFILE.metadata,
        arxiv_id=r"arXiv:(?P<arxiv_id>\d{4}\.\d{4,5})(?:v\d+)?",
        venue=r"(?P<venue>\d+(?:st|nd|rd|th) Conference on Neural Information Processing Systems"
        r" \(NIPS \d{4}\))",
    ),
)


def test_the_arxiv_id_and_the_venue_are_read_from_the_first_page() -> None:
    texts = [
        "Attention Is All You Need",
        "arXiv:1706.03762v7  [cs.CL]  2 Aug 2023",
        "31st Conference on Neural Information Processing Systems (NIPS 2017), Long Beach, CA.",
    ]

    assert read_stamps(texts, STAMPS) == (
        "1706.03762",
        "31st Conference on Neural Information Processing Systems (NIPS 2017)",
    )


def test_without_rules_no_stamps_are_read() -> None:
    assert read_stamps(["arXiv:1706.03762v7 [cs.CL]"], PROFILE) == ("", "")


def test_stamps_fill_the_meta_and_the_citation_wins_for_the_journal() -> None:
    front = FrontMatter(arxiv_id="1706.03762", venue="NIPS 2017")

    meta = build_meta(front, {}, STAMPS)

    assert (meta.arxiv_id, meta.journal) == ("1706.03762", "NIPS 2017")

    cited = FrontMatter(
        citation="Nibila Y (2026) A review. Front. Artif. Intell. 9:1748985. doi: 10.3389/x.1.",
        venue="NIPS 2017",
    )
    assert build_meta(cited, {}, PROFILE).journal == "Front. Artif. Intell."


def test_keywords_lose_the_label() -> None:
    assert parse_keywords("KEYWORDS deep learning, MRI", PROFILE) == ("deep learning", "MRI")


def test_the_citation_gives_the_bibliographic_fields() -> None:
    meta = build_meta(
        FrontMatter(
            title="A review",
            citation="Nibila Y and Sivagami M (2026) A review. Front. Artif. Intell. "
            "9:1748985. doi: 10.3389/frai.2026.1748985",
            copyright="© 2026 Nibila and Sivagami. This is an open-access article under the "
            "terms of the Creative Commons Attribution License (CC BY).",
        ),
        {},
        PROFILE,
    )

    assert (meta.year, meta.journal, meta.volume, meta.article_id) == (
        2026,
        "Front. Artif. Intell.",
        "9",
        "1748985",
    )
    assert meta.doi == "10.3389/frai.2026.1748985"
    assert meta.license is not None
    assert (meta.license.spdx, meta.license.holder) == ("CC-BY-4.0", "Nibila and Sivagami")
    assert meta.source_tier == "pdf"


def test_pdf_metadata_fills_the_gaps() -> None:
    meta = build_meta(FrontMatter(), {"title": "From the PDF"}, PROFILE)

    assert meta.title == "From the PDF"
    assert meta.license is None


def test_a_page_of_elements_reads_in_order() -> None:
    elements = page_elements(
        page_data(
            text_block("Right.", (305, 100, 546, 110)),
            text_block("Left.", (49, 200, 291, 210)),
        ),
        PROFILE,
    )

    assert [isinstance(e, TextElement) for e in elements] == [True, True]
    assert [e.bbox[0] for e in elements] == [49, 305]


# Text that belongs to a figure (issue #45)

LABELS = LabelRules(gap=4.0, max_words=6)
WITH_LABELS = replace(PROFILE, figures=replace(PROFILE.figures, labels=LABELS))
CROP_BOX = (58.0, 118.0, 282.0, 392.0)  # What the shapes (60, 120, 280, 390) give.


def test_a_short_block_that_touches_the_crop_joins_it() -> None:
    label = ((100.0, 108.0, 240.0, 119.0), 3)

    assert include_labels(CROP_BOX, [label], LABELS) == (58.0, 108.0, 282.0, 392.0)


def test_a_short_block_within_the_gap_joins_it() -> None:
    label = ((100.0, 108.0, 240.0, 114.0), 3)  # 4 points above the crop.

    assert include_labels(CROP_BOX, [label], LABELS)[1] == 108.0


def test_a_short_block_past_the_gap_stays_out() -> None:
    label = ((100.0, 100.0, 240.0, 113.0), 3)  # 5 points above.

    assert include_labels(CROP_BOX, [label], LABELS) == CROP_BOX


def test_a_paragraph_next_to_the_crop_stays_out() -> None:
    paragraph = ((49.0, 100.0, 291.0, 119.0), 40)

    assert include_labels(CROP_BOX, [paragraph], LABELS) == CROP_BOX


def test_a_label_next_to_a_label_joins_too() -> None:
    near = ((100.0, 108.0, 240.0, 119.0), 3)
    next_to_it = ((100.0, 98.0, 240.0, 105.0), 2)  # 3 points above the first.

    assert include_labels(CROP_BOX, [next_to_it, near], LABELS)[1] == 98.0


def label_page(*extra: TextBlock) -> PageData:
    return page_data(
        text_block("FIGURE 1 A chart.", (49, 400, 291, 408), font=LABEL, size=5.5),
        text_block("Scaled Dot-Product Attention", (100, 108, 240, 119), size=7.0),
        *extra,
        graphics=((60.0, 120.0, 280.0, 390.0),),
    )


def figure_boxes(elements) -> list[BBox]:
    return [e.crop_box for e in elements if hasattr(e, "crop_box")]


def test_a_label_above_a_figure_keeps_the_label_in_the_crop() -> None:
    problems: list[Problem] = []

    elements = page_elements(label_page(), WITH_LABELS, None, problems)

    assert figure_boxes(elements) == [(58.0, 108.0, 282.0, 392.0)]
    assert problems == []
    assert not [e for e in elements if isinstance(e, TextElement)]


def test_a_body_paragraph_above_the_figure_stays_in_the_text() -> None:
    words = " ".join(["word"] * 30)
    page = page_data(
        text_block("FIGURE 1 A chart.", (49, 400, 291, 408), font=LABEL, size=5.5),
        text_block(words, (49, 100, 291, 114)),
        graphics=((60.0, 120.0, 280.0, 390.0),),
    )

    elements = page_elements(page, WITH_LABELS, None, [])

    assert figure_boxes(elements) == [CROP_BOX]
    assert len([e for e in elements if isinstance(e, TextElement)]) == 1


def test_text_dropped_for_touching_a_figure_but_outside_it_is_reported() -> None:
    problems: list[Problem] = []

    elements = page_elements(label_page(), PROFILE, None, problems)

    assert figure_boxes(elements) == [CROP_BOX]
    [problem] = problems
    assert problem.code == "pdf.dropped_text"
    assert (problem.page, problem.bbox) == (2, (100.0, 108.0, 240.0, 119.0))
    assert "Scaled Dot-Product Attention" in problem.message


def test_text_inside_a_figure_is_not_reported() -> None:
    inside = text_block("axis label", (100, 200, 140, 208), size=7.0)
    problems: list[Problem] = []

    page_elements(
        page_data(
            text_block("FIGURE 1 A chart.", (49, 400, 291, 408), font=LABEL, size=5.5),
            inside,
            graphics=((60.0, 120.0, 280.0, 390.0),),
        ),
        PROFILE,
        None,
        problems,
    )

    assert problems == []


def test_the_adapter_hands_its_problems_to_the_caller() -> None:
    problems: list[Problem] = []

    assemble([label_page()], PROFILE, crop=CROP, pdf_metadata={}, problems=problems)

    assert [p.code for p in problems] == ["pdf.dropped_text"]
