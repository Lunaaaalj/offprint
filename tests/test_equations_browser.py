"""Equations with a browser each: determinism, the preamble, the baseline and the whole book.

Playwright's sync API can't nest, so these can't share a module with an open session.
"""

import base64
import io
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import numpy as np
import pytest
from math_corpus import DISPLAY, INLINE
from PIL import Image

from offprint.browser import chromium_page
from offprint.equations import (
    MathRenderError,
    MathRequest,
    MathSettings,
    engine_fingerprint,
    mathjax_session,
    typeset_math,
)
from offprint.equations.mathjax import ASSETS
from offprint.ir import Document, Equation, MathInline, Meta, Paragraph, Provenance, Text
from offprint.render.epub import render_epub
from offprint.render.epub.xhtml import RenderContext, render_runs

pytestmark = pytest.mark.usefixtures("chromium")

SETTINGS = MathSettings()
EM = SETTINGS.px_per_em
FLAT = r"\mathrm{n}"


@pytest.fixture(scope="module")
def inline_formulas(chromium: None) -> dict:
    with mathjax_session(SETTINGS) as running:
        running.set_preamble("")
        return {latex: running.render(MathRequest(latex, False)) for latex in (*INLINE, FLAT)}


def test_the_preamble_defines_macros_for_every_formula(chromium: None) -> None:
    with mathjax_session(SETTINGS) as running:
        assert running.set_preamble(r"\newcommand{\R}{\mathbb{R}}") is None
        first = running.render(MathRequest(r"\R", True))
        assert running.render(MathRequest(r"\R", True)) == first
        assert running.render(MathRequest(r"\mathbb{R}", True)) == first


def test_a_bad_preamble_is_an_error_and_leaves_no_definitions(chromium: None) -> None:
    with mathjax_session(SETTINGS) as running:
        assert running.set_preamble(r"\newcommand{\R}{x} \frac{") is not None
        with pytest.raises(MathRenderError):
            running.render(MathRequest(r"\R", True))


def test_rendering_is_reproducible(tmp_path: Path) -> None:
    """A second browser gives the same bytes, so a cache miss can't change a book."""
    requests = [MathRequest(latex, True) for latex in DISPLAY[:5]]
    with mathjax_session(SETTINGS) as first:
        one = [first.render(request) for request in requests]
    with mathjax_session(SETTINGS) as second:
        two = [second.render(request) for request in reversed(requests)]
    assert one == two[::-1]


def test_the_cache_gives_the_same_book_as_a_fresh_render(tmp_path: Path) -> None:
    runs = (MathInline("", INLINE[1]), Text(" and "), MathInline("", "x_i"))
    blocks = (
        Equation(id="e", alt="", number="1", latex=DISPLAY[0]),
        Paragraph(id="p", runs=runs),
    )
    doc = Document(
        meta=Meta(title="T"),
        blocks=blocks,
        provenance={block.id: Provenance(adapter="test") for block in blocks},
    )
    fresh = typeset_math(doc, cache_dir=tmp_path / "a")
    uncached = typeset_math(doc, cache_dir=tmp_path / "b")
    cached = typeset_math(doc, cache_dir=tmp_path / "a")
    assert fresh == uncached == cached

    books = []
    for name, result in (("fresh", fresh), ("cached", cached)):
        books.append(render_epub(result.doc, tmp_path / f"{name}.epub").path.read_bytes())
    assert books[0] == books[1]


def test_the_fingerprint_covers_the_vendored_files() -> None:
    assert len(engine_fingerprint()) == 64
    assert (ASSETS / "tex-svg-full.js").read_bytes().startswith(b"(function()")


# The criterion from #12: inline images sit on the text baseline. The preview (#7) doesn't exist
# yet, so this measures the same thing in Chromium with the book's real markup and stylesheet.

BASELINE_PAGE = """<!DOCTYPE html><html><head><style>{css}
body {{ margin: 0; font: {size}px/2 serif; color: black; background: white; }}
</style></head><body><p id="line">n<span id="probe"></span>{image}n</p></body></html>"""


def layout(result, size: int):
    """Set `result` in a line of text at `size` px. Returns the page and what was measured."""
    src = "data:image/png;base64," + base64.b64encode(result.png).decode()
    ctx = RenderContext(
        anchors={},
        cite_hrefs={},
        image_href=lambda _asset, _gray: src,
        math_boxes={"a": result.box},
    )
    image = render_runs((MathInline("", "x", "a"),), ctx)
    css = (files("offprint.render.epub") / "kindle.css").read_text()
    return BASELINE_PAGE.format(css=css, size=size, image=image)


MEASURE = """() => {
  const probe = document.getElementById('probe');
  probe.style.cssText = 'display:inline-block;width:0;height:0';
  const baseline = probe.getBoundingClientRect().bottom;
  const image = document.querySelector('img').getBoundingClientRect();
  return { baseline, bottom: image.bottom, height: image.height, width: image.width };
}"""


@pytest.mark.parametrize("latex", INLINE)
@pytest.mark.parametrize("size", [24, 40, 60])
def test_the_baseline_in_chromium_matches_the_depth(
    inline_formulas: dict, latex: str, size: int
) -> None:
    result = inline_formulas[latex]
    with chromium_page(1200, 300) as page:
        page.set_content(layout(result, size))
        page.wait_for_function("document.querySelector('img').complete")
        box = page.evaluate(MEASURE)
    assert box["bottom"] - box["baseline"] == pytest.approx(result.box.depth * size, abs=0.6)
    assert box["height"] == pytest.approx(result.box.height * size, abs=0.6)
    assert box["width"] == pytest.approx(result.box.width * size, abs=0.6)


def test_a_formula_lines_up_with_the_text_in_pixels(inline_formulas: dict) -> None:
    """`n` in the image and `n` in the text must end on the same pixel row."""
    result = inline_formulas[FLAT]
    with chromium_page(300, 200) as page:
        page.set_content(layout(result, EM))
        page.wait_for_function("document.querySelector('img').complete")
        box = page.evaluate(
            """() => {
              const r = document.querySelector('img').getBoundingClientRect();
              return { left: r.left, right: r.right };
            }"""
        )
        shot = page.screenshot()
    pixels = np.asarray(Image.open(io.BytesIO(shot)).convert("L"))

    def last_ink_row(left: int, right: int) -> int:
        return int(np.flatnonzero(pixels[:, left:right].min(axis=1) < 128)[-1])

    image_row = last_ink_row(int(box["left"]), int(box["right"]))
    text_row = last_ink_row(0, int(box["left"]))
    assert image_row == pytest.approx(text_row, abs=1)


def test_the_corpus_book_passes_epubcheck(tmp_path: Path) -> None:
    epubcheck = shutil.which("epubcheck")
    if epubcheck is None:
        pytest.skip("epubcheck is not on PATH (brew install epubcheck), so validity is unknown")
    blocks = [
        Equation(id=f"e{index}", alt="", number=str(index), latex=latex)
        for index, latex in enumerate(DISPLAY)
    ]
    blocks += [
        Paragraph(id=f"p{index}", runs=(Text("See "), MathInline("", latex), Text(".")))
        for index, latex in enumerate(INLINE)
    ]
    doc = Document(
        meta=Meta(title="T"),
        blocks=tuple(blocks),
        provenance={block.id: Provenance(adapter="test") for block in blocks},
    )
    result = typeset_math(doc, cache_dir=tmp_path / "cache")
    assert result.problems == ()
    path = render_epub(result.doc, tmp_path / "corpus.epub").path
    run = subprocess.run([epubcheck, str(path)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
