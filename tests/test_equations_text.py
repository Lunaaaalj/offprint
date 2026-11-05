"""The pure half of the equation stage: reducing LaTeX to a formula, and math that can be text."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from offprint.equations import clean_latex, simple_math
from offprint.equations.latex import split_tags
from offprint.ir import Italic, Sub, Sup, Text

PMC_WRAPPER = r"""\documentclass[12pt]{minimal}
\usepackage{amsmath}
\usepackage{wasysym}
\setlength{\oddsidemargin}{-69pt}
\begin{document}$$E = mc^2$$\end{document}"""


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        ("x", "x"),
        ("  x + y\n", "x + y"),
        ("$x$", "x"),
        ("$$x$$", "x"),
        (r"\[x\]", "x"),
        (r"\(x\)", "x"),
        (PMC_WRAPPER, "E = mc^2"),
        # Two formulas aren't one delimited formula.
        ("$a$ and $b$", "$a$ and $b$"),
        (r"\text{$a$}", r"\text{$a$}"),
        (r"\begin{align} a &= b \end{align}", r"\begin{align} a &= b \end{align}"),
        ("$", "$"),
        ("$$", "$$"),
        ("", ""),
    ],
)
def test_clean_latex(latex: str, expected: str) -> None:
    assert clean_latex(latex) == expected


@pytest.mark.parametrize(
    ("latex", "formula", "tag"),
    [
        ("a = b", "a = b", None),
        (r"a = b \tag{3.1}", "a = b ", "3.1"),
        (r"a = b \tag*{(A)}", "a = b ", "(A)"),
        (r"a \tag{1} \\ b \tag{2}", r"a  \\ b ", "1, 2"),
    ],
)
def test_tags_leave_the_formula(latex: str, formula: str, tag: str | None) -> None:
    assert split_tags(latex) == (formula, tag)


def italic(text: str) -> Italic:
    return Italic((Text(text),))


@pytest.mark.parametrize(
    ("latex", "runs"),
    [
        ("x", (italic("x"),)),
        ("x_i", (italic("x"), Sub((italic("i"),)))),
        ("x^2", (italic("x"), Sup((Text("2"),)))),
        (r"x_{t+1}", (italic("x"), Sub((italic("t"), Text("+"), Text("1"))))),
        (r"\alpha", (italic("α"),)),
        (r"\Omega", (Text("Ω"),)),
        ("n = 10", (italic("n"), Text(" = 10"))),
        (r"n \le 10", (italic("n"), Text(" ≤ 10"))),
        ("-1", (Text("−1"),)),
        ("a - b", (italic("a"), Text(" − "), italic("b"))),
        (r"\log n", (Text("log"), italic("n"))),
        (r"O(n)", (italic("O"), Text("("), italic("n"), Text(")"))),
        (r"a\,b", (italic("a"), italic("b"))),
    ],
)
def test_simple_math_becomes_text(latex: str, runs: tuple) -> None:
    assert simple_math(latex) == runs


@pytest.mark.parametrize(
    "latex",
    [
        "",
        "   ",
        r"\frac{a}{b}",
        r"\sqrt{2}",
        r"\sum_i x_i",
        r"\mathbf{x}",
        r"\hat{x}",
        r"\unknownmacro",
        # Stacked scripts would come out side by side.
        "x_i^2",
        "x^2_i",
        "x_{i_j}",
        "x^",
        "x_{",
        "x_{}",
        "{x}",
        "é",
    ],
)
def test_anything_else_stays_an_image(latex: str) -> None:
    assert simple_math(latex) is None


@given(st.text())
def test_any_input_is_handled(latex: str) -> None:
    simple_math(latex)
    clean_latex(latex)
    split_tags(latex)
