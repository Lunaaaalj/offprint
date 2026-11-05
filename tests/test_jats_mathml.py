"""MathML to LaTeX. Most cases are shapes from the fixture's 18 equations."""

import pytest
from lxml import etree

from offprint.adapters.jats.mathml import (
    UnsupportedMathML,
    mathml_to_latex,
    mathml_to_text,
    tex_text,
)


def math(inner: str) -> etree._Element:
    return etree.fromstring(f'<math xmlns="http://www.w3.org/1998/Math/MathML">{inner}</math>')


@pytest.mark.parametrize(
    ("inner", "latex"),
    [
        ("<mi>x</mi><mo>=</mo><mn>1</mn>", "x = 1"),
        ("<mi>α</mi><mi>x</mi>", r"\alpha x"),
        ("<mtext>aX</mtext>", r"\text{aX}"),
        ("<mi>sin</mi><mi>x</mi>", r"\sin x"),
        ("<mi>loss</mi>", r"\mathrm{loss}"),
        ('<mi mathvariant="bold">w</mi>', r"\mathbf{w}"),
        ("<mfrac><mi>a</mi><mi>b</mi></mfrac>", r"\frac{a}{b}"),
        ("<msqrt><mi>a</mi><mi>b</mi></msqrt>", r"\sqrt{a b}"),
        ("<mroot><mi>a</mi><mn>3</mn></mroot>", r"\sqrt[3]{a}"),
        ("<msub><mi>x</mi><mi>i</mi></msub>", "x_{i}"),
        ("<msup><mi>x</mi><mn>2</mn></msup>", "x^{2}"),
        ("<msubsup><mi>x</mi><mi>i</mi><mn>2</mn></msubsup>", "x_{i}^{2}"),
        ("<msub><mrow><mi>a</mi><mi>b</mi></mrow><mi>i</mi></msub>", "{a b}_{i}"),
        ("<msub><mtext>x</mtext><mn>1</mn></msub>", r"\text{x}_{1}"),
        ("<munderover><mo>∑</mo><mi>a</mi><mi>b</mi></munderover>", r"\sum_{a}^{b}"),
        ("<munder><mo>max</mo><mi>a</mi></munder>", r"\max_{a}"),
        ("<munder><mi>x</mi><mi>a</mi></munder>", r"\underset{a}{x}"),
        ("<mover><mi>y</mi><mo>^</mo></mover>", r"\hat{y}"),
        ("<mover><mi>y</mi><mo>∧</mo></mover>", r"\hat{y}"),
        ("<mover><mi>x</mi><mo>¯</mo></mover>", r"\overline{x}"),
        ("<mover><mi>x</mi><mi>a</mi></mover>", r"\overset{a}{x}"),
        ('<mfenced open="[" close="]"><mi>a</mi><mi>b</mi></mfenced>', "[ a , b ]"),
        ("<mo>{</mo><mi>a</mi><mo>}</mo>", r"\{ a \}"),
        ("<mi>a</mi><mo>%</mo>", r"a \%"),
        ("<mo>∑</mo><mi>m</mi>", r"\sum m"),
        ("<mstyle><mpadded><mi>x</mi></mpadded></mstyle>", "x"),
        ("<mphantom><mi>x</mi></mphantom><mi>y</mi>", "y"),
        (
            "<semantics><mi>x</mi>"
            '<annotation encoding="application/x-tex">\\tilde x</annotation></semantics>',
            r"\tilde x",
        ),
        ("<semantics><mi>x</mi></semantics>", "x"),
    ],
)
def test_conversion(inner: str, latex: str) -> None:
    assert mathml_to_latex(math(inner)) == latex


def test_the_fixtures_one_cell_table_is_only_a_wrapper() -> None:
    inner = (
        '<mtable class="eqnarray" columnalign="left"><mtr><mtd><mtext>Y</mtext><mo>=</mo>'
        "<mtext>b</mtext></mtd></mtr></mtable>"
    )

    assert mathml_to_latex(math(inner)) == r"\text{Y} = \text{b}"


def test_a_real_table_becomes_an_array() -> None:
    inner = (
        '<mtable columnalign="left"><mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr>'
        "<mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr></mtable>"
    )

    assert mathml_to_latex(math(inner)) == r"\begin{array}{ll} a & b \\ c & d \end{array}"


def test_a_labelled_row_leaves_the_label_to_the_equation_number() -> None:
    inner = "<mtable><mlabeledtr><mtd><mn>1</mn></mtd><mtd><mi>a</mi></mtd></mlabeledtr></mtable>"

    assert mathml_to_latex(math(inner)) == "a"


def test_the_fixtures_no_break_spaces_become_latex_spaces() -> None:
    assert mathml_to_latex(math("<mi>a</mi><mtext> </mtext><mo> </mo>")) == r"a \  \,"


def test_invisible_operators_vanish() -> None:
    assert mathml_to_latex(math("<mi>a</mi><mo>⁢</mo><mi>b</mi>")) == "a b"


@pytest.mark.parametrize(
    "inner",
    [
        "<mglyph/>",
        "<mmultiscripts><mi>x</mi></mmultiscripts>",
        "<mi>𝔘</mi>",
        "<mfrac><mi>a</mi></mfrac>",
        "<msub><mi>a</mi></msub>",
    ],
)
def test_what_has_no_mapping_is_an_error_not_a_gap(inner: str) -> None:
    with pytest.raises(UnsupportedMathML):
        mathml_to_latex(math(inner))


def test_text_reads_sub_and_superscripts() -> None:
    inner = (
        "<mover><mi>y</mi><mo>^</mo></mover><mo>=</mo><msub><mi>x</mi><mi>i</mi></msub>"
        "<msup><mi>z</mi><mn>2</mn></msup><mfrac><mi>a</mi><mi>b</mi></mfrac>"
        "<msqrt><mi>c</mi></msqrt>"
    )

    assert mathml_to_text(math(inner)) == "y^=x_iz^2(a)/(b)√(c)"


def test_text_ignores_annotations() -> None:
    inner = "<semantics><mi>x</mi><annotation>tex</annotation></semantics>"

    assert mathml_to_text(math(inner)) == "x"


def test_tex_text_escapes_what_latex_reserves() -> None:
    assert tex_text("h_t 50% $x {y}") == r"\text{h\_t 50\% \$x \{y\}}"
