"""Inline JATS to runs: styles, links, citations, formulas and whitespace."""

import pytest
from lxml import etree

from offprint.adapters.jats.inline import (
    collapse_label,
    inline_runs,
    read_formula,
    tex_source,
    tidy_runs,
)
from offprint.ir import Bold, Cite, Italic, Link, MathInline, Problem, Sub, Sup, Text

NAMESPACES = (
    'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML"'
)
MATH = "<mml:math><mml:msub><mml:mi>x</mml:mi><mml:mi>i</mml:mi></mml:msub></mml:math>"


def runs_of(inner: str, problems: list[Problem] | None = None):
    element = etree.fromstring(f"<p {NAMESPACES}>{inner}</p>")
    return inline_runs(element, [] if problems is None else problems)


def test_styles_nest() -> None:
    assert runs_of("a <bold>b <italic>c</italic></bold>") == (
        Text("a "),
        Bold((Text("b "), Italic((Text("c"),)))),
    )


def test_sub_and_sup() -> None:
    assert runs_of("x<sub>1</sub>y<sup>2</sup>") == (
        Text("x"),
        Sub((Text("1"),)),
        Text("y"),
        Sup((Text("2"),)),
    )


def test_the_text_after_an_element_is_kept() -> None:
    assert runs_of("<bold>a</bold> tail") == (Bold((Text("a"),)), Text(" tail"))


def test_styling_the_ir_has_no_room_for_keeps_its_text() -> None:
    assert runs_of("a<sc>b</sc><underline>c</underline>") == (Text("abc"),)


def test_a_bibliography_xref_is_a_cite() -> None:
    assert runs_of('(<xref rid="B107" ref-type="bibr">Zhang, 2021</xref>)') == (
        Text("("),
        Cite("B107", (Text("Zhang, 2021"),)),
        Text(")"),
    )


def test_an_xref_with_several_targets_links_to_the_first() -> None:
    assert runs_of('<xref rid="B1 B2">1</xref>') == (Cite("B1", (Text("1"),)),)


def test_an_empty_xref_leaves_nothing() -> None:
    assert runs_of('a<xref rid="aff1" ref-type="aff"/>') == (Text("a"),)


def test_ext_link() -> None:
    assert runs_of('<ext-link xlink:href="https://a.org/x">here</ext-link>') == (
        Link("https://a.org/x", (Text("here"),)),
    )


def test_a_doi_link_becomes_a_url() -> None:
    inner = '<ext-link ext-link-type="doi" xlink:href="10.1/x">the paper</ext-link>'

    assert runs_of(inner) == (Link("https://doi.org/10.1/x", (Text("the paper"),)),)


def test_a_bare_uri_is_its_own_text() -> None:
    assert runs_of("<uri>https://a.org</uri>") == (Link("https://a.org", (Text("https://a.org"),)),)


def test_a_link_to_something_that_isnt_a_url_keeps_its_text() -> None:
    inner = '<ext-link ext-link-type="pmid" xlink:href="123">PMID 123</ext-link>'

    assert runs_of(inner) == (Text("PMID 123"),)


def test_email() -> None:
    assert runs_of("<email>a@example.com</email>") == (
        Link("mailto:a@example.com", (Text("a@example.com"),)),
    )


def test_a_line_break_keeps_words_apart() -> None:
    assert runs_of("one<break/>two") == (Text("one two"),)


def test_paragraphs_in_a_cell_keep_words_apart() -> None:
    assert runs_of("<p>one</p><p>two</p>") == (Text("one two"),)


def test_metadata_never_reaches_the_text() -> None:
    assert runs_of('a<alt-text>no</alt-text><target id="x"/>') == (Text("a"),)


def test_an_unknown_element_keeps_its_text_and_is_reported() -> None:
    problems: list[Problem] = []

    assert runs_of("a<wobble>b</wobble>", problems) == (Text("ab"),)
    assert [problem.code for problem in problems] == ["jats.unmapped_inline"]


def test_inline_mathml_keeps_text_and_latex() -> None:
    assert runs_of(f"<inline-formula>{MATH}</inline-formula>") == (MathInline("x_i", "x_{i}"),)


def test_inline_tex_math() -> None:
    assert runs_of(r"<inline-formula><tex-math>$a^2$</tex-math></inline-formula>") == (
        MathInline("a^2", "a^2"),
    )


def test_a_math_element_outside_inline_formula() -> None:
    assert runs_of(MATH) == (MathInline("x_i", "x_{i}"),)


def test_an_inline_formula_with_only_text_stays_text() -> None:
    assert runs_of("<inline-formula>p &lt; 0.05</inline-formula>") == (Text("p < 0.05"),)


def test_an_inline_graphic_falls_back_on_its_alt_text_and_is_reported() -> None:
    problems: list[Problem] = []
    inner = '<inline-graphic xlink:href="a.gif"><alt-text>beta</alt-text></inline-graphic>'

    assert runs_of(inner, problems) == (Text("beta"),)
    assert [problem.code for problem in problems] == ["jats.inline_graphic"]


def test_an_inline_graphic_with_no_alt_text_leaves_a_visible_marker() -> None:
    problems: list[Problem] = []

    assert runs_of('<inline-graphic xlink:href="a.gif"/>', problems) == (Text("[image]"),)
    assert "a.gif" in problems[0].message


# Whitespace


def test_whitespace_collapses_across_runs() -> None:
    assert tidy_runs((Text("a  "), Bold((Text("  b\n"),)), Text(" c"))) == (
        Text("a "),
        Bold((Text("b "),)),
        Text("c"),
    )


def test_the_ends_are_trimmed_through_nested_runs() -> None:
    assert tidy_runs((Text("\n a"), Bold((Text("b \n"),)), Text(" \n"))) == (
        Text("a"),
        Bold((Text("b"),)),
    )


def test_a_style_that_holds_only_space_goes_away() -> None:
    assert tidy_runs((Text("a"), Bold((Text("  "),)))) == (Text("a"),)


def test_no_break_spaces_survive() -> None:
    assert tidy_runs((Text("a  b"),)) == (Text("a  b"),)


def test_neighbouring_text_joins() -> None:
    assert tidy_runs((Text("a"), Text("b"))) == (Text("ab"),)


# Formulas


@pytest.mark.parametrize(
    ("tex", "expected"),
    [
        ("x^2", "x^2"),
        ("$x^2$", "x^2"),
        ("$$x^2$$", "x^2"),
        (r"\[x^2\]", "x^2"),
        (r"\(x^2\)", "x^2"),
        (
            r"\documentclass[12pt]{minimal}\usepackage{amsmath}\begin{document}$$x^2$$\end{document}",
            "x^2",
        ),
    ],
)
def test_tex_source(tex: str, expected: str) -> None:
    assert tex_source(tex) == expected


def formula(inner: str):
    problems: list[Problem] = []
    element = etree.fromstring(f"<disp-formula {NAMESPACES}>{inner}</disp-formula>")
    return read_formula(element, problems), problems


def test_tex_wins_over_mathml() -> None:
    found, _ = formula(f"<alternatives><tex-math>y_i</tex-math>{MATH}</alternatives>")

    assert (found.latex, found.text) == ("y_i", "x_i")


def test_unconvertible_mathml_becomes_text_and_is_reported() -> None:
    found, problems = formula('<mml:math><mml:mi>a</mml:mi><mml:mglyph alt="b"/></mml:math>')

    assert found.latex == r"\text{a}"
    assert [problem.code for problem in problems] == ["jats.math_fallback"]


def test_a_formula_with_no_maths_has_no_latex() -> None:
    found, problems = formula("<label>(1)</label>a + b")

    assert (found.latex, found.text) == (None, "a + b")
    assert problems == []


@pytest.mark.parametrize(("label", "number"), [("(1)", "1"), ("2.1.", "2.1"), ("S1:", "S1")])
def test_collapse_label(label: str, number: str) -> None:
    assert collapse_label(etree.fromstring(f"<label>{label}</label>")) == number


def test_no_label() -> None:
    assert collapse_label(None) == ""
