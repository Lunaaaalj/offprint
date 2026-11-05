"""The one renderer: MathJax, vendored, running in the offline Chromium the cover already uses.

docs/equations.md explains why. The page does the typesetting. This side turns its answer into a
grayscale PNG with black ink on transparency, and refuses an image with nothing on it.
"""

import base64
import hashlib
import importlib.metadata
import io
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from importlib.resources import files
from typing import Any

from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from offprint.browser import BrowserUnavailableError, chromium_page
from offprint.equations.model import (
    MathRenderError,
    MathRequest,
    MathSettings,
    RenderedMath,
    round_em,
)
from offprint.ir import MathBox

ASSETS = files("offprint.equations") / "assets"
_SIDE_MARGIN_PX = 2
_ASSET_NAMES = ("page.html", "tex-svg-full.js", "render.js")


@cache
def engine_fingerprint() -> str:
    """Identify everything that shapes the pixels. Playwright's version pins Chromium's build."""
    digest = hashlib.sha256(importlib.metadata.version("playwright").encode())
    for name in _ASSET_NAMES:
        digest.update((ASSETS / name).read_bytes())
    return digest.hexdigest()


class MathJaxSession:
    """A loaded page. `render` keeps no state between formulas apart from the preamble."""

    def __init__(self, page: Page, settings: MathSettings) -> None:
        self._page = page
        self._settings = settings

    def set_preamble(self, preamble: str) -> str | None:
        """Define the paper's macros for what follows. Returns TeX's error, if there is one."""
        return self._call("offprint.setPreamble(preamble)", preamble=preamble).get("error")

    def render(self, request: MathRequest) -> RenderedMath:
        """Render one formula, or raise `MathRenderError` with TeX's message."""
        px_per_em = self._settings.px_per_em
        answer = self._call(
            "offprint.render(latex, display, pxPerEm)",
            latex=request.latex,
            display=request.display,
            pxPerEm=px_per_em,
        )
        if error := answer.get("error"):
            raise MathRenderError(error)
        png, width = _ink_on_transparency(base64.b64decode(answer["png"]))
        return RenderedMath(
            png=png,
            width=width,
            height=answer["height"],
            box=MathBox(
                width=round_em(width / px_per_em),
                height=round_em(answer["height"] / px_per_em),
                depth=round_em(answer["depth"] / px_per_em),
            ),
            system_font=answer["systemFont"],
        )

    def _call(self, expression: str, **arguments: Any) -> dict[str, Any]:
        names = ", ".join(arguments)
        script = f"({{ {names} }}) => {expression}"
        try:
            return self._page.evaluate(script, arguments)
        except PlaywrightError as error:
            raise MathRenderError(f"Chromium failed: {error}") from error


@contextmanager
def mathjax_session(settings: MathSettings) -> Iterator[MathJaxSession]:
    """Start Chromium and load MathJax. Raises `BrowserUnavailableError` without Chromium."""
    with chromium_page(16, 16) as page:
        try:
            page.set_content((ASSETS / "page.html").read_text())
            page.add_script_tag(content=(ASSETS / "tex-svg-full.js").read_text())
            page.evaluate("MathJax.startup.promise")
            page.add_script_tag(content=(ASSETS / "render.js").read_text())
        except PlaywrightError as error:
            raise BrowserUnavailableError(f"MathJax didn't load: {error}") from error
        yield MathJaxSession(page, settings)


def _ink_on_transparency(png: bytes) -> tuple[bytes, int]:
    """Reduce the canvas's RGBA to gray and alpha, and crop the sides to the ink. Pure.

    Rows stay, because the baseline is counted from the bottom. Returns the PNG and its width.
    """
    image = Image.open(io.BytesIO(png)).convert("LA")
    ink = image.getchannel("A").getbbox()
    if ink is None:
        raise MathRenderError("the formula rendered as a blank image")
    left = max(ink[0] - _SIDE_MARGIN_PX, 0)
    right = min(ink[2] + _SIDE_MARGIN_PX, image.width)
    image = image.crop((left, 0, right, image.height))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), image.width
