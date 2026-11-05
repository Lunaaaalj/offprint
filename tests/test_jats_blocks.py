"""Mapping `<body>` and `<back>`: each block shape, with graphics loaded from a fake."""

import pytest

from offprint.adapters.jats import JatsResult, map_article, parse_article
from offprint.adapters.jats.blocks import label_number
from offprint.ir import (
    Asset,
    Block,
    Bold,
    Equation,
    Figure,
    Heading,
    ListItem,
    Paragraph,
    Reference,
    Table,
    Text,
    validate,
)
from offprint.render.epub.xhtml import plain_text

NAMESPACES = (
    'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML"'
)


def load(name: str) -> Asset | None:
    if name.startswith("absent"):
        return None
    return Asset(id=name, mime="image/jpeg", bytes=b"image")


def mapped(body: str, back: str = "", front: str = "") -> JatsResult:
    xml = (
        f"<article {NAMESPACES}><front><article-meta>{front}</article-meta></front>"
        f"<body>{body}</body><back>{back}</back></article>"
    )
    result, _ = map_article(parse_article(xml.encode()), load)
    return result


def blocks(body: str, back: str = "", front: str = "") -> tuple[Block, ...]:
    return mapped(body, back, front).document.blocks


def of_type(found: tuple[Block, ...], kind: type) -> list:
    return [block for block in found if isinstance(block, kind)]


def graphic(name: str = "f.jpg", inner: str = "") -> str:
    return f'<graphic xlink:href="{name}">{inner}</graphic>'


# Sections


def test_sections_nest_and_keep_their_numbers() -> None:
    found = blocks(
        "<sec><label>1</label><title>One</title><p>Text</p>"
        "<sec><label>1.1.</label><title>Sub</title></sec></sec>"
    )

    assert [(type(b).__name__, getattr(b, "level", None)) for b in found] == [
        ("Heading", 1),
        ("Paragraph", None),
        ("Heading", 2),
    ]
    assert found[0].number == "1"
    assert found[2].number == "1.1"


def test_a_section_with_no_title_adds_no_level() -> None:
    found = blocks("<sec><title>One</title><sec><sec><title>Deep</title></sec></sec></sec>")

    assert [block.level for block in found] == [1, 2]


def test_every_block_has_provenance_that_finds_its_element() -> None:
    result = mapped("<sec><title>One</title><p>Text</p></sec>")

    assert validate(result.document) == []
    provenance = result.document.provenance[result.document.blocks[1].id]
    assert provenance.adapter == "jats"
    assert provenance.note == "/article/body/sec/p"


# Paragraphs


def test_a_paragraph_splits_around_a_block_inside_it() -> None:
    found = blocks(
        '<p>Before <fig id="F1"><label>Figure 1</label>' + graphic() + "</fig> after.</p>"
    )

    assert [type(block) for block in found] == [Paragraph, Figure, Paragraph]
    assert (plain_text(found[0].runs), plain_text(found[2].runs)) == ("Before", "after.")


def test_a_paragraph_holding_only_a_figure_leaves_no_empty_paragraph() -> None:
    assert [type(b) for b in blocks("<p><fig>" + graphic() + "</fig></p>")] == [Figure]


# Lists


def test_a_list() -> None:
    found = blocks(
        '<list list-type="order"><list-item><p>One</p></list-item>'
        "<list-item><p>Two</p></list-item></list>"
    )

    assert [plain_text(item.runs) for item in found] == ["One", "Two"]
    assert all(item.ordered and item.depth == 0 for item in found)


def test_a_bullet_list_isnt_ordered() -> None:
    found = blocks('<list list-type="bullet"><list-item><p>One</p></list-item></list>')

    assert not found[0].ordered


def test_a_nested_list_goes_one_deeper() -> None:
    found = blocks(
        "<list><list-item><p>Outer</p><list><list-item><p>Inner</p></list-item></list>"
        "</list-item></list>"
    )

    assert [item.depth for item in found] == [0, 1]


def test_an_items_label_and_paragraphs_stay_in_one_item() -> None:
    found = blocks("<list><list-item><label>a)</label><p>One</p><p>Two</p></list-item></list>")

    assert [plain_text(item.runs) for item in found] == ["a) One Two"]


def test_definitions_become_list_items() -> None:
    found = blocks(
        "<def-list><def-item><term>AD</term><def><p>Alzheimer's</p></def></def-item></def-list>"
    )

    assert plain_text(found[0].runs) == "AD Alzheimer's"
    assert found[0].runs[0] == Bold((Text("AD"),))


# Figures


@pytest.mark.parametrize(
    ("label", "number"),
    [
        ("Figure 1", "1"),
        ("FIGURE 1.", "1"),
        ("Fig. S2", "S2"),
        ("Figs 3", "3"),
        ("Table 2:", "2"),
        ("Scheme 1", "Scheme 1"),
        ("Figure 1—figure supplement 1", "1—figure supplement 1"),
    ],
)
def test_label_number(label: str, number: str) -> None:
    assert label_number(label) == number


def test_a_figure() -> None:
    result = mapped(
        '<fig id="F1"><label>Figure 1</label><caption><p><bold>(A)</bold> Axial.</p></caption>'
        + graphic(inner="<alt-text>An MRI</alt-text>")
        + "</fig>"
    )

    figure = result.document.blocks[0]
    assert (figure.number, figure.asset, figure.alt) == ("1", "f.jpg", "An MRI")
    assert plain_text(figure.caption) == "(A) Axial."
    assert result.document.assets["f.jpg"].mime == "image/jpeg"


def test_machine_generated_alt_text_isnt_trusted() -> None:
    """The fixture's Figure 1, a brain MRI, is described as a policy-change framework."""
    alt = '<alt-text content-type="machine-generated">Conceptual framework</alt-text>'

    figure = blocks("<fig><label>Figure 1</label>" + graphic(inner=alt) + "</fig>")[0]

    assert figure.alt is None


def test_a_figures_credit_stays_with_its_caption() -> None:
    found = blocks(
        "<fig><label>Figure 1</label><caption><p>Cap.</p></caption><attrib>From X.</attrib>"
        "<permissions><copyright-statement>© Y</copyright-statement></permissions>"
        + graphic()
        + "</fig>"
    )

    assert plain_text(found[0].caption) == "Cap. From X. © Y"


def test_a_figure_with_two_images_keeps_both() -> None:
    result = mapped("<fig><label>Figure 1</label>" + graphic("a.jpg") + graphic("b.jpg") + "</fig>")

    assert [figure.number for figure in result.document.blocks] == ["1", "1.2"]
    assert validate(result.document) == []


def test_unlabelled_figures_get_unique_numbers() -> None:
    result = mapped("<fig>" + graphic("a.jpg") + "</fig><fig>" + graphic("b.jpg") + "</fig>")

    assert [figure.number for figure in result.document.blocks] == ["U1", "U2"]


def test_a_shared_image_is_stored_once() -> None:
    result = mapped("<fig>" + graphic() + "</fig><fig>" + graphic() + "</fig>")

    assert list(result.document.assets) == ["f.jpg"]
    assert len(result.document.blocks) == 2


def test_a_group_keeps_its_caption_and_every_figure() -> None:
    found = blocks(
        "<fig-group><caption><p>Both.</p></caption>"
        "<fig><label>Figure 1A</label>" + graphic("a.jpg") + "</fig>"
        "<fig><label>Figure 1B</label>" + graphic("b.jpg") + "</fig></fig-group>"
    )

    assert plain_text(found[0].runs) == "Both."
    assert [figure.number for figure in found[1:]] == ["1A", "1B"]


def test_a_figure_with_no_graphic_keeps_its_caption_and_is_reported() -> None:
    result = mapped("<fig><label>Figure 1</label><caption><p>Cap.</p></caption></fig>")

    assert plain_text(result.document.blocks[0].runs) == "Cap."
    assert [problem.code for problem in result.problems] == ["jats.figure_without_graphic"]


def test_a_missing_graphic_is_reported_and_mapping_goes_on() -> None:
    xml = (
        f"<article {NAMESPACES}><body><fig>{graphic('absent.jpg')}</fig>"
        f"<fig>{graphic('../etc/passwd')}</fig><fig>{graphic('there.jpg')}</fig></body></article>"
    )

    result, missing = map_article(parse_article(xml.encode()), load)

    assert missing == ("absent.jpg", "../etc/passwd")
    assert [block.asset for block in result.document.blocks] == ["there.jpg"]


# Tables


def test_a_table() -> None:
    table = blocks(
        '<table-wrap id="T1"><label>Table 1</label><caption><title>Name.</title><p>More.</p>'
        "</caption><table><thead><tr><th>a</th></tr></thead><tbody><tr><td>b</td></tr></tbody>"
        "</table><table-wrap-foot><fn><label>*</label><p>Note.</p></fn></table-wrap-foot>"
        "</table-wrap>"
    )[0]

    assert table.number == "1"
    assert plain_text(table.caption) == "Name. More."
    assert plain_text(table.notes) == "* Note."
    assert table.rows == (((Text("b"),),),)


def test_an_image_of_a_table_becomes_a_figure_and_is_reported() -> None:
    result = mapped("<table-wrap><label>Table 2</label>" + graphic() + "</table-wrap>")

    figure = result.document.blocks[0]
    assert isinstance(figure, Figure)
    assert figure.number == "Table 2"
    assert [problem.code for problem in result.problems] == ["jats.table_as_figure"]


def test_a_table_model_we_cant_read_keeps_its_text_and_is_reported() -> None:
    result = mapped("<table-wrap><label>Table 2</label><cals>cell text</cals></table-wrap>")

    assert "cell text" in plain_text(result.document.blocks[0].runs)
    assert "jats.unmapped_element" in [problem.code for problem in result.problems]


# Equations


MATH = "<mml:math><mml:mi>x</mml:mi></mml:math>"


def test_an_equation_from_mathml() -> None:
    equation = blocks(f'<disp-formula id="EQ1">{MATH}<label>(1)</label></disp-formula>')[0]

    assert (equation.number, equation.latex, equation.alt) == ("1", "x", "x")
    assert equation.asset is None


def test_an_equation_from_tex() -> None:
    equation = blocks(r"<disp-formula><tex-math>\alpha</tex-math></disp-formula>")[0]

    assert equation.latex == r"\alpha"


def test_an_equation_with_only_an_image_uses_it() -> None:
    equation = blocks("<disp-formula>" + graphic("eq.gif") + "</disp-formula>")[0]

    assert (equation.latex, equation.asset) == (None, "eq.gif")


def test_maths_beats_an_image_of_the_same_equation() -> None:
    equation = blocks(f"<disp-formula>{MATH}{graphic('absent.gif')}</disp-formula>")[0]

    assert (equation.latex, equation.asset) == ("x", None)


def test_a_formula_of_plain_text_is_kept_and_reported() -> None:
    result = mapped("<disp-formula><label>(1)</label>a + b</disp-formula>")

    equation = result.document.blocks[0]
    assert equation.latex == r"\text{a + b}"
    assert validate(result.document) == []
    assert [problem.code for problem in result.problems] == ["jats.math_fallback"]


def test_an_empty_formula_is_reported_and_writes_nothing() -> None:
    result = mapped("<disp-formula/>")

    assert result.document.blocks == ()
    assert [problem.code for problem in result.problems] == ["jats.empty_formula"]


def test_a_grouped_equation_isnt_lost() -> None:
    found = blocks(f"<disp-formula-group><disp-formula>{MATH}</disp-formula></disp-formula-group>")

    assert isinstance(found[0], Equation)


# Back matter


def titles(found: tuple[Block, ...]) -> list[str]:
    return [plain_text(block.runs) for block in found if isinstance(block, Heading)]


def test_references_come_last_with_their_keys() -> None:
    found = blocks(
        "<sec><title>One</title></sec>",
        '<ref-list><title>Refs</title><ref id="B1"><mixed-citation>Paper. doi: '
        '<pub-id pub-id-type="doi">10.1/x</pub-id></mixed-citation></ref></ref-list>'
        "<sec><title>After</title></sec>",
    )

    assert titles(found) == ["One", "After", "Refs"]
    reference = of_type(found, Reference)[0]
    assert (reference.key, reference.doi) == ("B1", "10.1/x")


def test_a_reference_list_with_no_title_is_still_a_heading() -> None:
    assert titles(blocks("", '<ref-list><ref id="B1"><note>x</note></ref></ref-list>')) == [
        "References"
    ]


def test_acknowledgments_get_a_heading_even_with_no_title() -> None:
    assert titles(blocks("", "<ack><p>Thanks.</p></ack>")) == ["Acknowledgments"]


def test_an_ack_keeps_its_own_title() -> None:
    assert titles(blocks("", "<ack><title>Thank you</title><p>x</p></ack>")) == ["Thank you"]


def test_back_sections_are_top_level() -> None:
    found = blocks("", '<sec sec-type="COI-statement"><title>Conflict</title><p>None.</p></sec>')

    assert found[0].level == 1


def test_a_footnote_group_gets_a_heading() -> None:
    found = blocks("", '<fn-group><fn id="n1"><label>1</label><p>A note.</p></fn></fn-group>')

    assert titles(found) == ["Notes"]
    assert plain_text(of_type(found, Paragraph)[0].runs) == "1 A note."


def test_editorial_credits_go_to_the_front_matter() -> None:
    found = blocks(
        "<sec><title>One</title></sec>",
        '<fn-group><fn fn-type="edited-by"><p>Edited by: A</p></fn>'
        '<fn fn-type="reviewed-by"><p>Reviewed by: B</p></fn></fn-group>',
    )

    assert titles(found) == ["One"]
    assert [block.role for block in found[:2]] == ["small", "small"]


def test_appendices_nest_under_their_group() -> None:
    found = blocks(
        "",
        "<app-group><title>Appendix</title><app><title>A</title><p>x</p></app></app-group>",
    )

    assert [(plain_text(b.runs), b.level) for b in of_type(found, Heading)] == [
        ("Appendix", 1),
        ("A", 2),
    ]


def test_an_appendix_with_only_a_label_uses_it() -> None:
    assert titles(blocks("", "<app-group><app><label>Appendix A</label></app></app-group>")) == [
        "Appendix A"
    ]


def test_funding_from_the_front_matter_is_a_back_matter_heading() -> None:
    found = blocks(
        "",
        '<ref-list><ref id="B1"><note>x</note></ref></ref-list>',
        "<funding-group><funding-statement>Funded by X.</funding-statement></funding-group>",
    )

    assert titles(found) == ["Funding", "References"]
    assert plain_text(of_type(found, Paragraph)[0].runs) == "Funded by X."


def test_a_funding_section_isnt_repeated() -> None:
    found = blocks(
        "",
        '<sec sec-type="funding-information"><title>Funding</title><p>X</p></sec>',
        "<funding-group><funding-statement>X</funding-statement></funding-group>",
    )

    assert titles(found) == ["Funding"]


def test_a_conflict_note_in_the_front_matter_is_a_back_matter_heading() -> None:
    found = blocks(
        "",
        "",
        '<author-notes><fn fn-type="COI-statement"><p>None declared.</p></fn></author-notes>',
    )

    assert titles(found) == ["Conflict of interest"]


def test_floats_kept_apart_from_the_text_arent_lost() -> None:
    xml = (
        f"<article {NAMESPACES}><body><p>x</p></body><floats-group><fig>{graphic()}</fig>"
        "</floats-group></article>"
    )

    result, _ = map_article(parse_article(xml.encode()), load)

    assert isinstance(result.document.blocks[-1], Figure)


# The front matter and what doesn't map


def test_the_abstract_paragraphs_lead_the_book() -> None:
    found = blocks("<sec><title>One</title></sec>", "", "<abstract><p>A.</p><p>B.</p></abstract>")

    assert [block.role for block in of_type(found, Paragraph)] == ["abstract", "abstract"]
    assert isinstance(found[2], Heading)


def test_quotes_and_boxes_keep_their_content() -> None:
    found = blocks(
        "<disp-quote><p>Said.</p><attrib>Her</attrib></disp-quote>"
        "<boxed-text><title>Box</title><p>In it.</p></boxed-text>"
    )

    assert [plain_text(block.runs) for block in found] == ["Said.", "Her", "Box", "In it."]


def test_a_supplement_says_it_exists() -> None:
    found = blocks(
        "<supplementary-material><label>Data S1</label><caption><p>Raw data.</p></caption>"
        "</supplementary-material>"
    )

    assert plain_text(found[0].runs) == "Data S1 Raw data."
    assert found[0].role == "small"


def test_an_unknown_block_keeps_its_text_and_is_reported() -> None:
    result = mapped("<wobble>Some text</wobble>")

    assert plain_text(result.document.blocks[0].runs) == "Some text"
    assert "jats.unmapped_element" in [problem.code for problem in result.problems]


def test_a_sub_article_is_reported() -> None:
    xml = f"<article {NAMESPACES}><body><p>x</p></body><sub-article/></article>"

    result, _ = map_article(parse_article(xml.encode()), load)

    assert "jats.unmapped_element" in [problem.code for problem in result.problems]


def test_numbers_that_collide_fail_validate_instead_of_vanishing() -> None:
    table = "<table-wrap><label>Table 1</label><table><tr><td>a</td></tr></table></table-wrap>"

    result = mapped(table + table)

    assert "table.duplicate_number" in [problem.code for problem in validate(result.document)]
    assert len(of_type(result.document.blocks, Table)) == 2


def test_an_empty_list_item_leaves_nothing() -> None:
    assert of_type(blocks("<list><list-item><p/></list-item></list>"), ListItem) == []
