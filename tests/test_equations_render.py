"""The corpus through real MathJax in real Chromium: pixels, metrics and errors."""

import io

import numpy as np
import pytest
from math_corpus import CORPUS
from PIL import Image

from offprint.equations import MathRenderError, MathRequest, MathSettings, mathjax_session
from offprint.equations.mathjax import MathJaxSession

pytestmark = pytest.mark.usefixtures("chromium")

SETTINGS = MathSettings()
EM = SETTINGS.px_per_em


@pytest.fixture(scope="module")
def session(chromium: None) -> MathJaxSession:
    with mathjax_session(SETTINGS) as running:
        assert running.set_preamble("") is None
        yield running


def alpha(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).getchannel("A"))


def ink_rows(png: bytes) -> np.ndarray:
    return np.flatnonzero(alpha(png).max(axis=1) > 128)


def test_the_corpus_is_about_thirty_equations_of_every_kind() -> None:
    assert len(CORPUS) >= 30
    assert {kind for kind, _ in CORPUS} == {
        "fraction",
        "sum",
        "matrix",
        "cases",
        "aligned",
        "symbols",
        "inline",
    }


@pytest.mark.parametrize(("kind", "latex"), CORPUS)
def test_the_corpus_renders(session: MathJaxSession, kind: str, latex: str) -> None:
    result = session.render(MathRequest(latex, kind != "inline"))
    image = Image.open(io.BytesIO(result.png))
    assert image.format == "PNG"
    assert image.mode == "LA"
    assert image.size == (result.width, result.height)
    assert not result.system_font
    # Ink is black, and the background is transparent.
    pixels = np.asarray(image)
    assert pixels[..., 0][pixels[..., 1] > 250].max() < 16
    assert pixels[..., 1][0].max() == 0 and pixels[..., 1][-1].max() == 0
    assert (pixels[..., 1][:, 0].max(), pixels[..., 1][:, -1].max()) == (0, 0)
    assert result.box.width == pytest.approx(result.width / EM, abs=1e-3)
    assert result.box.height == pytest.approx(result.height / EM, abs=1e-3)
    assert 0 <= result.box.depth < result.box.height


def test_inline_and_display_differ(session: MathJaxSession) -> None:
    latex = r"\sum_{i=1}^n x_i"
    display = session.render(MathRequest(latex, True))
    inline = session.render(MathRequest(latex, False))
    assert inline.height < display.height


def test_the_depth_is_where_the_ink_of_a_flat_formula_ends(session: MathJaxSession) -> None:
    """`n` sits on the baseline and has no descender."""
    result = session.render(MathRequest(r"\mathrm{n}", False))
    baseline_row = result.height - round(result.box.depth * EM)
    assert ink_rows(result.png)[-1] == pytest.approx(baseline_row - 1, abs=1)


def test_a_descender_goes_below_the_baseline(session: MathJaxSession) -> None:
    flat = session.render(MathRequest(r"\mathrm{n}", False))
    deep = session.render(MathRequest(r"\mathrm{p}", False))
    assert deep.box.depth > flat.box.depth + 0.1


def test_rules_in_arrays_are_drawn(session: MathJaxSession) -> None:
    """They take their stroke from MathJax's stylesheet, which an SVG image doesn't inherit."""

    def ink(latex: str) -> int:
        return int((alpha(session.render(MathRequest(latex, True)).png) > 128).sum())

    plain = r"\begin{array}{cc} 1 & 2 \\ 3 & 4 \end{array}"
    assert ink(r"\begin{array}{c|c} 1 & 2 \\ 3 & 4 \end{array}") > ink(plain) + 100
    assert ink(r"\begin{array}{cc} 1 & 2 \\ \hline 3 & 4 \end{array}") > ink(plain) + 100


def test_multline_is_as_wide_as_it_says_not_as_wide_as_a_page(session: MathJaxSession) -> None:
    result = session.render(MathRequest(r"\begin{multline} a \\ b \end{multline}", True))
    assert result.box.width < 25


@pytest.mark.parametrize(
    ("latex", "message"),
    [
        (r"\nosuchmacro x", "Undefined control sequence"),
        (r"\frac{a}{b", "Missing close brace"),
        (r"\begin{tikzpicture}\end{tikzpicture}", "Unknown environment"),
        (r"\def\a{\a}\a", "recursive"),
        (r"\usepackage{x}", "Undefined control sequence"),
        (r"\phantom{x}", "blank"),
        (r"\,", "blank"),
        (r"a \tag{1}", "page"),
    ],
)
def test_what_cant_be_drawn_is_an_error_not_an_image(
    session: MathJaxSession, latex: str, message: str
) -> None:
    with pytest.raises(MathRenderError, match=message):
        session.render(MathRequest(latex, True))


@pytest.mark.parametrize("latex", [r"\mathbb{1}", r"\mathds{1}", r"\mathbbm{ 1 }"])
def test_the_indicator_function_needs_no_system_font(session: MathJaxSession, latex: str) -> None:
    assert not session.render(MathRequest(latex, True)).system_font


def test_a_glyph_mathjax_lacks_is_flagged(session: MathJaxSession) -> None:
    assert session.render(MathRequest(r"\text{日本}", True)).system_font


@pytest.mark.parametrize(
    "latex",
    [
        r"\bm{x}",
        r"\mathds{1}",
        r"\mathbbm{1}",
        r"\nicefrac{1}{2}",
        r"\ensuremath{x}",
        r"\vspace{1em}x",
        r"\coloneqq",
        r"\begin{dcases} a \\ b \end{dcases}",
        r"\begin{subequations}\begin{align} a &= b \end{align}\end{subequations}",
        r"\begin{eqnarray} a &=& b \end{eqnarray}",
        r"\begin{align} a &= b \label{eq:same} \end{align}",
        r"\ce{H2O}",
    ],
)
def test_what_papers_use_beyond_the_corpus(session: MathJaxSession, latex: str) -> None:
    session.render(MathRequest(latex, True))


def test_a_label_can_repeat(session: MathJaxSession) -> None:
    latex = r"\begin{align} a &= b \label{eq:twice} \end{align}"
    assert session.render(MathRequest(latex, True)) == session.render(MathRequest(latex, True))


@pytest.mark.parametrize(
    "definition",
    [
        r"\newcommand{\leak}{x}\leak",
        r"\def\leak{x}\leak",
        r"\let\leak=x \leak",
        r"\DeclareMathOperator{\leak}{x}\leak",
        r"\newenvironment{leak}{}{}\begin{leak}x\end{leak}",
    ],
)
def test_a_formula_cant_change_the_next_one(session: MathJaxSession, definition: str) -> None:
    """Otherwise a formula's meaning would depend on what the cache already held."""
    session.render(MathRequest(definition, True))
    with pytest.raises(MathRenderError):
        session.render(MathRequest(r"\leak \begin{leak}x\end{leak}", True))


def test_a_redefinition_doesnt_last_either(session: MathJaxSession) -> None:
    latex = r"\alpha"
    before = session.render(MathRequest(latex, True))
    session.render(MathRequest(r"\renewcommand{\alpha}{x}\alpha", True))
    assert session.render(MathRequest(latex, True)) == before
