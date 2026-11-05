"""The equation stage around its renderer: what it asks for, caches, applies and reports."""

import json
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from offprint.browser import BrowserUnavailableError
from offprint.equations import (
    MathRenderError,
    MathRequest,
    MathSettings,
    RenderedMath,
    apply_rendered,
    asset_id,
    collect_requests,
    typeset_math,
)
from offprint.equations.cache import cache_key, load, store
from offprint.ir import (
    Asset,
    Bold,
    Document,
    Equation,
    Figure,
    Heading,
    Italic,
    MathBox,
    MathInline,
    Meta,
    Paragraph,
    Provenance,
    Reference,
    Sub,
    Table,
    Text,
    validate,
)

BOX = MathBox(width=2.0, height=1.5, depth=0.25)
HARD = r"\frac{a}{b}"
CROP = Asset(id="crop", mime="image/png", bytes=b"crop")


def doc_of(*blocks, meta: Meta | None = None, assets: tuple[Asset, ...] = ()) -> Document:
    return Document(
        meta=meta or Meta(title="T"),
        blocks=blocks,
        assets={asset.id: asset for asset in assets},
        provenance={block.id: Provenance(adapter="test") for block in blocks},
    )


def paragraph(*runs, block_id: str = "p") -> Paragraph:
    return Paragraph(id=block_id, runs=runs)


def rendered(latex: str = "") -> RenderedMath:
    return RenderedMath(png=f"png of {latex}".encode(), width=120, height=90, box=BOX)


class FakeSession:
    """Stands in for Chromium: records calls and fails the formulas it's told to."""

    def __init__(self, failing: frozenset[str] = frozenset(), preamble_error: str | None = None):
        self.failing = failing
        self.preamble_error = preamble_error
        self.preambles: list[str] = []
        self.requests: list[MathRequest] = []
        self.starts = 0

    @contextmanager
    def __call__(self, _settings: MathSettings) -> Iterator["FakeSession"]:
        self.starts += 1
        yield self

    def set_preamble(self, preamble: str) -> str | None:
        self.preambles.append(preamble)
        return self.preamble_error

    def render(self, request: MathRequest) -> RenderedMath:
        self.requests.append(request)
        if request.latex in self.failing:
            raise MathRenderError("Undefined control sequence")
        return rendered(request.latex)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


def test_requests_come_from_every_place_math_can_be() -> None:
    doc = doc_of(
        Equation(id="e", alt="", latex=HARD),
        Heading(id="h", level=1, runs=(MathInline("", r"\sqrt{1}"),)),
        paragraph(Italic((Bold((MathInline("", r"\sqrt{2}"),)),))),
        Reference(id="r", runs=(MathInline("", r"\sqrt{3}"),)),
        Figure(id="f", number="1", asset="crop", caption=(MathInline("", r"\sqrt{4}"),)),
        Table(
            id="t",
            number="1",
            caption=(MathInline("", r"\sqrt{5}"),),
            header=((MathInline("", r"\sqrt{6}"),),),
            rows=(((MathInline("", r"\sqrt{7}"),),),),
            notes=(MathInline("", r"\sqrt{8}"),),
        ),
        meta=Meta(title="T", abstract=(MathInline("", r"\sqrt{9}"),)),
        assets=(CROP,),
    )
    assert collect_requests(doc) == (
        MathRequest(r"\sqrt{9}", False),
        MathRequest(HARD, True),
        *(MathRequest(f"\\sqrt{{{n}}}", False) for n in range(1, 9)),
    )


def test_a_repeated_formula_is_rendered_once_per_style() -> None:
    doc = doc_of(
        Equation(id="e1", alt="", latex=HARD),
        Equation(id="e2", alt="", latex=f"$${HARD}$$"),
        paragraph(MathInline("", HARD), MathInline("", f"${HARD}$")),
    )
    assert collect_requests(doc) == (MathRequest(HARD, True), MathRequest(HARD, False))


def test_what_needs_no_image_is_not_requested() -> None:
    doc = doc_of(
        Equation(id="e1", alt="cropped", asset="crop"),
        Equation(id="e2", alt="", latex=HARD, asset="crop"),
        paragraph(MathInline("x + y"), MathInline("", "x_i"), MathInline("", HARD, "crop")),
        assets=(CROP,),
    )
    assert collect_requests(doc) == ()


def test_a_document_without_latex_is_untouched_and_starts_nothing(
    session: FakeSession, tmp_path: Path
) -> None:
    doc = doc_of(
        Equation(id="e", alt="E", number="1", asset="crop"),
        paragraph(Text("t"), MathInline("x")),
        assets=(CROP,),
    )
    result = typeset_math(doc, cache_dir=tmp_path / "cache", session=session)
    assert result.doc == doc
    assert result.problems == ()
    assert session.starts == 0
    assert not (tmp_path / "cache").exists()


def test_an_equation_gets_an_image(session: FakeSession, tmp_path: Path) -> None:
    doc = doc_of(Equation(id="e", alt="a over b", number="1", latex=f"$${HARD}$$"))
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    equation = result.doc.blocks[0]
    assert (equation.latex, equation.alt, equation.number) == (HARD, "a over b", "1")
    asset = result.doc.assets[equation.asset]
    assert asset.id == equation.asset
    assert (asset.mime, asset.bytes, asset.box) == ("image/png", rendered(HARD).png, BOX)
    assert (asset.width, asset.height) == (120, 90)
    assert result.problems == ()
    assert validate(result.doc) == []


def test_a_tag_becomes_the_number_unless_the_adapter_has_one(
    session: FakeSession, tmp_path: Path
) -> None:
    doc = doc_of(
        Equation(id="e1", alt="", latex=r"a \tag{7}"),
        Equation(id="e2", alt="", number="2", latex=r"b \tag{7}"),
    )
    blocks = typeset_math(doc, cache_dir=tmp_path, session=session).doc.blocks
    assert [block.number for block in blocks] == ["7", "2"]
    assert [request.latex for request in session.requests] == ["a ", "b "]


def test_inline_math_is_text_when_simple_and_an_image_otherwise(
    session: FakeSession, tmp_path: Path
) -> None:
    doc = doc_of(
        paragraph(
            Text("Let "),
            MathInline("", "x_i"),
            Text(" and "),
            Sub((MathInline("", HARD),)),
        )
    )
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    key = next(iter(result.doc.assets))
    assert result.doc.blocks[0].runs == (
        Text("Let "),
        Italic((Text("x"),)),
        Sub((Italic((Text("i"),)),)),
        Text(" and "),
        Sub((MathInline("", HARD, key),)),
    )
    assert session.requests == [MathRequest(HARD, False)]
    assert validate(result.doc) == []


def test_simple_math_needs_no_browser(session: FakeSession, tmp_path: Path) -> None:
    doc = doc_of(paragraph(MathInline("", r"\alpha")))
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    assert result.doc.blocks[0].runs == (Italic((Text("α"),)),)
    assert session.starts == 0


def test_a_formula_in_the_abstract_is_rendered(session: FakeSession, tmp_path: Path) -> None:
    doc = doc_of(meta=Meta(title="T", abstract=(MathInline("", HARD),)))
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    assert result.doc.meta.abstract[0].asset in result.doc.assets
    assert validate(result.doc) == []


def test_a_failed_formula_stays_and_is_reported(tmp_path: Path) -> None:
    doc = doc_of(
        Equation(id="e", alt="fallback", latex=r"\bad"),
        paragraph(MathInline("", r"\bad"), block_id="p"),
        paragraph(MathInline("", HARD), block_id="q"),
    )
    session = FakeSession(failing=frozenset({r"\bad"}))
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    equation, failed, good = result.doc.blocks
    assert equation.asset is None and equation.latex == r"\bad"
    assert failed.runs == (MathInline("", r"\bad"),)
    assert good.runs[0].asset is not None
    assert [(p.code, p.block_id) for p in result.problems] == [
        ("math.render_failed", "e"),
        ("math.render_failed", "p"),
    ]
    assert "Undefined control sequence" in result.problems[0].message


def test_a_failure_is_not_cached(tmp_path: Path) -> None:
    doc = doc_of(Equation(id="e", alt="", latex=r"\bad"))
    first = FakeSession(failing=frozenset({r"\bad"}))
    typeset_math(doc, cache_dir=tmp_path, session=first)
    second = FakeSession()
    result = typeset_math(doc, cache_dir=tmp_path, session=second)
    assert result.doc.blocks[0].asset is not None
    assert second.starts == 1


def test_without_chromium_every_formula_stays_and_one_problem_says_so(tmp_path: Path) -> None:
    @contextmanager
    def no_browser(_settings: MathSettings) -> Iterator[None]:
        raise BrowserUnavailableError("run `uv run playwright install chromium`")
        yield

    doc = doc_of(
        Equation(id="e", alt="", latex=HARD),
        paragraph(MathInline("", r"\sqrt{2}")),
    )
    result = typeset_math(doc, cache_dir=tmp_path, session=no_browser)
    assert [problem.code for problem in result.problems] == ["math.renderer_unavailable"]
    assert "2 formula(s)" in result.problems[0].message
    assert result.doc.blocks[0].asset is None
    assert result.doc.blocks[1].runs == (MathInline("", r"\sqrt{2}"),)


def test_a_glyph_from_the_system_is_reported_from_the_cache_too(tmp_path: Path) -> None:
    class SystemFont(FakeSession):
        def render(self, request: MathRequest) -> RenderedMath:
            return replace(rendered(request.latex), system_font=True)

    doc = doc_of(Equation(id="e", alt="", latex=r"\text{日本}"))
    for session in (SystemFont(), FakeSession()):
        result = typeset_math(doc, cache_dir=tmp_path, session=session)
        assert [p.code for p in result.problems] == ["math.system_font"]


def test_the_preamble_reaches_the_renderer_and_the_key(
    session: FakeSession, tmp_path: Path
) -> None:
    doc = doc_of(Equation(id="e", alt="", latex=r"\R"))
    plain = typeset_math(doc, cache_dir=tmp_path, session=session)
    defined = typeset_math(doc, preamble=r"\newcommand{\R}{x}", cache_dir=tmp_path, session=session)
    assert session.preambles == ["", r"\newcommand{\R}{x}"]
    assert plain.doc.blocks[0].asset != defined.doc.blocks[0].asset


def test_a_bad_preamble_is_reported_and_nothing_is_cached(tmp_path: Path) -> None:
    doc = doc_of(Equation(id="e", alt="", latex=HARD))
    broken = FakeSession(preamble_error="Missing close brace")
    result = typeset_math(doc, preamble=r"\def", cache_dir=tmp_path, session=broken)
    assert [problem.code for problem in result.problems] == ["math.preamble_failed"]
    assert result.doc.blocks[0].asset is not None

    # On a second run the report must still appear: it can't be hidden by a cache hit.
    again = typeset_math(doc, preamble=r"\def", cache_dir=tmp_path, session=broken)
    assert [problem.code for problem in again.problems] == ["math.preamble_failed"]


def test_the_cache_avoids_the_browser_and_changes_nothing(
    session: FakeSession, tmp_path: Path
) -> None:
    doc = doc_of(Equation(id="e", alt="", latex=HARD), paragraph(MathInline("", r"\sqrt{2}")))
    first = typeset_math(doc, cache_dir=tmp_path, session=session)
    second = typeset_math(doc, cache_dir=tmp_path, session=session)
    assert session.starts == 1
    assert first == second


def test_only_cache_misses_are_rendered(session: FakeSession, tmp_path: Path) -> None:
    typeset_math(doc_of(Equation(id="e", alt="", latex="a")), cache_dir=tmp_path, session=session)
    session.requests.clear()
    doc = doc_of(Equation(id="e", alt="", latex="a"), Equation(id="f", alt="", latex="b"))
    typeset_math(doc, cache_dir=tmp_path, session=session)
    assert [request.latex for request in session.requests] == ["b"]


def test_an_unwritable_cache_costs_a_report_not_the_equation(
    session: FakeSession, tmp_path: Path
) -> None:
    (tmp_path / "math").write_text("a file where the directory should be")
    doc = doc_of(Equation(id="e", alt="", latex=HARD))
    result = typeset_math(doc, cache_dir=tmp_path, session=session)
    assert [problem.code for problem in result.problems] == ["math.cache_unwritable"]
    assert result.doc.blocks[0].asset is not None


REQUEST = MathRequest("a", True)


@pytest.mark.parametrize(
    ("changed"),
    [
        (MathRequest("b", True), "", MathSettings(), "e"),
        (MathRequest("a", False), "", MathSettings(), "e"),
        (REQUEST, r"\def\a{}", MathSettings(), "e"),
        (REQUEST, "", MathSettings(px_per_em=30), "e"),
        (REQUEST, "", MathSettings(), "another engine"),
    ],
)
def test_everything_that_shapes_the_pixels_is_in_the_key(changed: tuple) -> None:
    assert cache_key(*changed) != cache_key(REQUEST, "", MathSettings(), "e")


def test_the_key_is_stable() -> None:
    assert cache_key(REQUEST, "", MathSettings(), "e") == cache_key(
        MathRequest("a", True), "", MathSettings(), "e"
    )


def test_an_entry_round_trips(tmp_path: Path) -> None:
    store(tmp_path, "k", rendered("a"))
    assert load(tmp_path, "k") == rendered("a")
    assert [path.name for path in tmp_path.iterdir()] == ["k.json"]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        "{}",
        json.dumps({"png": "%%%", "width": 1, "height": 1, "box": {}, "system_font": False}),
        json.dumps({"png": "", "width": 1, "height": 1, "box": {"nope": 1}, "system_font": False}),
    ],
)
def test_a_damaged_entry_is_a_miss(tmp_path: Path, content: str) -> None:
    (tmp_path / "k.json").write_text(content)
    assert load(tmp_path, "k") is None


def test_a_failed_write_leaves_nothing_behind(tmp_path: Path) -> None:
    store(tmp_path, "k", rendered("a"))
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(OSError):
            store(tmp_path, "other", rendered("b"))
    finally:
        tmp_path.chmod(stat.S_IRWXU)
    assert [path.name for path in tmp_path.iterdir()] == ["k.json"]


def test_applying_nothing_keeps_failed_math_visible() -> None:
    doc = doc_of(Equation(id="e", alt="", latex=f"${HARD}$"))
    result, problems = apply_rendered(doc, {})
    assert result.blocks[0].latex == HARD
    assert problems == ()


def test_asset_ids_are_short_and_safe() -> None:
    assert asset_id("ab" * 32) == "math-" + "ab" * 16
