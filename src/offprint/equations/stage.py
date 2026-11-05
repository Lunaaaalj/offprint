"""The equation stage: `Equation(latex)` and `MathInline(latex)` in, images and text out.

It runs between the adapter and the EPUB renderer, so adapters stay out of images and renderers
out of TeX, and every later output gets the same equations. `collect_requests` and
`apply_rendered` are pure. Only `typeset_math` touches Chromium and the disk.
"""

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from offprint.browser import BrowserUnavailableError
from offprint.equations import cache
from offprint.equations.latex import clean_latex, split_tags
from offprint.equations.mathjax import engine_fingerprint, mathjax_session
from offprint.equations.model import (
    MathRenderError,
    MathRequest,
    MathSettings,
    RenderedMath,
    TypesetResult,
)
from offprint.equations.simple import simple_math
from offprint.ir import (
    Asset,
    Block,
    Document,
    Equation,
    MathInline,
    Problem,
    Run,
    Runs,
    map_block_runs,
    map_runs,
)
from offprint.sources import load_config

type Outcome = RenderedMath | str
"""A rendered formula, or why it couldn't be rendered."""


class Session(Protocol):
    def set_preamble(self, preamble: str) -> str | None: ...

    def render(self, request: MathRequest) -> RenderedMath: ...


type SessionFactory = Callable[[MathSettings], AbstractContextManager[Session]]


def collect_requests(doc: Document) -> tuple[MathRequest, ...]:
    """List the distinct formulas that need an image, in document order. Pure."""
    found: dict[MathRequest, None] = {}

    def visit(run: Run) -> Runs:
        if (request := _inline_request(run)) is not None:
            found[request] = None
        return (run,)

    map_runs(doc.meta.abstract, visit)
    for block in doc.blocks:
        if (request := _equation_request(block)) is not None:
            found[request] = None
        map_block_runs(block, visit)
    return tuple(found)


def _equation_request(block: Block) -> MathRequest | None:
    if isinstance(block, Equation) and block.latex and block.asset is None:
        return MathRequest(split_tags(clean_latex(block.latex))[0], display=True)
    return None


def _inline_request(run: Run) -> MathRequest | None:
    if isinstance(run, MathInline) and run.latex and run.asset is None:
        latex = clean_latex(run.latex)
        return None if simple_math(latex) else MathRequest(latex, display=False)
    return None


def asset_id(key: str) -> str:
    """An asset's id, from its cache key, so a formula has one id in every run. Pure."""
    return f"math-{key[:32]}"


@dataclass(frozen=True, slots=True)
class Resolved:
    outcome: Outcome
    key: str


def apply_rendered(
    doc: Document, resolved: Mapping[MathRequest, Resolved]
) -> tuple[Document, tuple[Problem, ...]]:
    """Point the IR at its images and report what couldn't be drawn. Pure.

    A formula that failed keeps its LaTeX and gets no asset, so the renderer shows it as text.
    """
    assets = dict(doc.assets)
    problems: list[Problem] = []

    def use(request: MathRequest, block_id: str | None) -> str | None:
        entry = resolved.get(request)
        if entry is None:
            return None
        if isinstance(entry.outcome, str):
            message = f"can't render {request.latex!r}: {entry.outcome}"
            problems.append(Problem("math.render_failed", message, block_id))
            return None
        rendered = entry.outcome
        if rendered.system_font:
            message = f"{request.latex!r} needs a glyph MathJax lacks, so a system font drew it"
            problems.append(Problem("math.system_font", message, block_id))
        identifier = asset_id(entry.key)
        assets[identifier] = Asset(
            id=identifier,
            mime="image/png",
            bytes=rendered.png,
            width=rendered.width,
            height=rendered.height,
            box=rendered.box,
        )
        return identifier

    def inline(block_id: str | None) -> Callable[[Run], Runs]:
        def apply(run: Run) -> Runs:
            if not isinstance(run, MathInline) or not run.latex or run.asset is not None:
                return (run,)
            latex = clean_latex(run.latex)
            if text := simple_math(latex):
                return text
            image = use(MathRequest(latex, display=False), block_id)
            return (replace(run, latex=latex, asset=image),)

        return apply

    def block_with_images(block: Block) -> Block:
        if (request := _equation_request(block)) is not None:
            number = block.number or split_tags(clean_latex(block.latex))[1]
            return replace(block, latex=request.latex, number=number, asset=use(request, block.id))
        return map_block_runs(block, inline(block.id))

    abstract = map_runs(doc.meta.abstract, inline(None))
    blocks = tuple(block_with_images(block) for block in doc.blocks)
    return replace(
        doc, meta=replace(doc.meta, abstract=abstract), blocks=blocks, assets=assets
    ), tuple(problems)


def typeset_math(
    doc: Document,
    *,
    preamble: str = "",
    settings: MathSettings | None = None,
    cache_dir: Path | None = None,
    session: SessionFactory = mathjax_session,
) -> TypesetResult:
    """Give every LaTeX formula in `doc` an image, or a reported reason why not.

    `preamble` holds the paper's `\\newcommand`s. A document with no LaTeX comes back unchanged,
    without touching Chromium or the cache: the PDF adapter's cropped equations stay as they are.
    """
    settings = settings or MathSettings()
    requests = collect_requests(doc)
    if not requests:
        return TypesetResult(apply_rendered(doc, {})[0])

    root = (cache_dir or load_config().cache_dir) / cache.CACHE_SUBDIR
    engine = engine_fingerprint()
    keys = {request: cache.cache_key(request, preamble, settings, engine) for request in requests}
    found = {request: cache.load(root, key) for request, key in keys.items()}
    missing = [request for request in requests if found[request] is None]

    outcomes, problems = _render_missing(missing, preamble, settings, session)
    # Formulas rendered without the paper's macros mustn't be cached as if they had them.
    if not any(problem.code == "math.preamble_failed" for problem in problems):
        for request, outcome in outcomes.items():
            if isinstance(outcome, RenderedMath):
                problems += _store(root, keys[request], outcome, request)

    resolved = {
        request: Resolved(found[request] or outcomes[request], keys[request])
        for request in requests
        if request in outcomes or found[request] is not None
    }
    result, applied = apply_rendered(doc, resolved)
    return TypesetResult(result, tuple(problems) + applied)


def _render_missing(
    missing: list[MathRequest],
    preamble: str,
    settings: MathSettings,
    session: SessionFactory,
) -> tuple[dict[MathRequest, Outcome], list[Problem]]:
    if not missing:
        return {}, []
    outcomes: dict[MathRequest, Outcome] = {}
    problems: list[Problem] = []
    try:
        with session(settings) as renderer:
            if error := renderer.set_preamble(preamble):
                message = f"the paper's macros were ignored: {error}"
                problems.append(Problem("math.preamble_failed", message))
            for request in missing:
                try:
                    outcomes[request] = renderer.render(request)
                except MathRenderError as error:
                    outcomes[request] = str(error)
    except (BrowserUnavailableError, MathRenderError) as error:
        message = f"{len(missing)} formula(s) stay as text: {error}"
        problems.append(Problem("math.renderer_unavailable", message))
    return outcomes, problems


def _store(root: Path, key: str, rendered: RenderedMath, request: MathRequest) -> list[Problem]:
    try:
        cache.store(root, key, rendered)
    except OSError as error:
        message = f"can't cache {request.latex!r}: {error}"
        return [Problem("math.cache_unwritable", message)]
    return []
