"""Compose a cover: choose a hero, fill the template, render it and check the result."""

import base64
import re
from dataclasses import dataclass
from html import escape
from importlib.resources import files
from io import BytesIO
from string import Template

from PIL import Image

from offprint.browser import chromium_page
from offprint.cover.hero import Hero, HeroSelector, select_hero, treat_hero
from offprint.cover.layout import Element, contrast_problems, overflow_problems
from offprint.cover.motif import HEIGHT, WIDTH, motif_seed, network_svg
from offprint.cover.text import (
    DEFAULT_KICKER,
    format_authors,
    format_citation,
    format_imprint,
    split_kicker,
)
from offprint.ir import Document, Problem

ASSETS = files("offprint.cover") / "assets"


@dataclass(frozen=True, slots=True)
class CoverOptions:
    """`kicker` overrides the article type read from the title; `select_hero` swaps the rule."""

    kicker: str | None = None
    select_hero: HeroSelector = select_hero


@dataclass(frozen=True, slots=True)
class Rendered:
    png: bytes
    elements: list[Element]
    problems: list[Problem]


class CoverLayoutError(ValueError):
    """The rendered cover failed a check. `problems` holds them, with stable codes."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(f"{p.code}: {p.message}" for p in problems))
        self.problems = problems


def _inline_fonts(css: str) -> str:
    """Embed the fonts, so rendering depends on neither file paths nor the system's fonts."""

    def embed(match: re.Match[str]) -> str:
        font = base64.b64encode((ASSETS / match[1]).read_bytes()).decode()
        return f"url(data:font/woff2;base64,{font})"

    return re.sub(r"url\((fonts/[^)]+)\)", embed, css)


def _hero_html(hero: Hero | None) -> str:
    if hero is None:
        return ""
    buffer = BytesIO()
    treat_hero(hero.image).save(buffer, format="PNG")
    image = base64.b64encode(buffer.getvalue()).decode()
    return f'<div class="hero"><img alt="" src="data:image/png;base64,{image}"></div>'


def build_html(doc: Document, options: CoverOptions, hero: Hero | None) -> str:
    """Build the complete, self-contained page for this paper."""
    title, title_kicker = split_kicker(doc.meta.title)
    return Template((ASSETS / "cover.html").read_text()).substitute(
        css=_inline_fonts((ASSETS / "cover.css").read_text()),
        hero=_hero_html(hero),
        motif=network_svg(motif_seed(doc.meta), has_hero=hero is not None),
        kicker=escape(options.kicker or title_kicker or DEFAULT_KICKER),
        title=escape(title),
        authors=escape(format_authors(doc.meta.authors)),
        citation=escape(format_citation(doc.meta)),
        imprint=escape(format_imprint(doc.meta)),
    )


def render(html: str) -> Rendered:
    """Fit a page's text, screenshot it and check the result."""
    with chromium_page(WIDTH, HEIGHT) as page:
        page.set_content(html, wait_until="load")
        reported = page.evaluate((ASSETS / "layout.js").read_text())
        png = page.screenshot(type="png")
        page.add_style_tag(content="[data-text] { visibility: hidden; }")
        bare_png = page.screenshot(type="png")

    elements = [
        Element(item["name"], tuple(item["box"]), tuple(item["ink"]), tuple(item["colour"]))
        for item in reported
    ]
    bare_page = Image.open(BytesIO(bare_png)).convert("RGB")
    problems = overflow_problems(elements, WIDTH, HEIGHT) + contrast_problems(elements, bare_page)
    return Rendered(png, elements, problems)


def generate_cover(doc: Document, options: CoverOptions | None = None) -> bytes:
    """Render a 1600x2560 PNG cover. Raises `CoverLayoutError` rather than ship a broken one."""
    options = options or CoverOptions()
    rendered = render(build_html(doc, options, options.select_hero(doc)))
    if rendered.problems:
        raise CoverLayoutError(rendered.problems)
    return rendered.png
