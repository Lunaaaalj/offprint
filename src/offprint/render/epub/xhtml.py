"""Turn IR runs and blocks into XHTML. All text reaches the output through `esc`."""

import html
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import groupby
from urllib.parse import quote, urlsplit

from offprint.ir import (
    Block,
    Bold,
    Cite,
    Equation,
    Figure,
    Heading,
    Italic,
    Link,
    ListItem,
    MathBox,
    MathInline,
    Paragraph,
    Problem,
    Reference,
    Run,
    Runs,
    Sub,
    Sup,
    Table,
    Text,
)
from offprint.render.epub.sanitize import strip_invalid_xml

logger = logging.getLogger("offprint.render.epub")

_LINK_SCHEMES = {"http", "https", "mailto"}
_URL_SAFE = "%/:=&?~#+!$,;'@()*[]-._"


def esc(text: str) -> str:
    return html.escape(text, quote=True)


@dataclass
class RenderContext:
    """What rendering a block needs to know about the rest of the book."""

    anchors: Mapping[str, str]
    cite_hrefs: Mapping[str, str]
    image_href: Callable[[str, bool], str]
    """Return an asset's href, given its id and whether it should be grayscale."""
    problems: list[Problem] = field(default_factory=list)
    math_boxes: Mapping[str, MathBox] = field(default_factory=dict)
    """The size of each rendered formula, by asset id."""

    def report(self, code: str, message: str, block_id: str | None = None) -> None:
        logger.warning("%s: %s", code, message)
        self.problems.append(Problem(code, message, block_id))

    def clean(self, markup: str, where: str, block_id: str | None = None) -> str:
        """Strip what XHTML can't hold from finished markup, reporting what was removed."""
        cleaned, removed = strip_invalid_xml(markup)
        if removed:
            shown = ", ".join(dict.fromkeys(removed))
            self.report(
                "epub.invalid_xml_chars",
                f"stripped {len(removed)} invalid character(s) ({shown}) from {where}",
                block_id,
            )
        return cleaned


def plain_text(runs: Runs) -> str:
    """Return runs as one line of clean text, for labels and `alt` attributes."""
    text = "".join(_run_text(run) for run in runs)
    return " ".join(strip_invalid_xml(text)[0].split())


def _run_text(run: Run) -> str:
    match run:
        case Text(text):
            return text
        case MathInline(text, latex):
            return text or latex or ""
        case Italic(runs) | Bold(runs) | Sup(runs) | Sub(runs) | Link(_, runs) | Cite(_, runs):
            return "".join(_run_text(inner) for inner in runs)


def safe_href(href: str) -> str | None:
    """Return `href` as a valid external URL, or None if it can't go in an EPUB."""
    url = strip_invalid_xml(href)[0].strip()
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises for a port that isn't a number
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _LINK_SCHEMES or (scheme != "mailto" and not parts.hostname):
        return None
    return quote(url, safe=_URL_SAFE)


def doi_url(doi: str) -> str:
    return "https://doi.org/" + quote(strip_invalid_xml(doi)[0].strip(), safe="/:;()._-")


def render_runs(
    runs: Runs, ctx: RenderContext, block_id: str | None = None, in_link: bool = False
) -> str:
    return "".join(_render_run(run, ctx, block_id, in_link) for run in runs)


def _render_run(run: Run, ctx: RenderContext, block_id: str | None, in_link: bool) -> str:
    def wrapped(tag: str, runs: Runs) -> str:
        return f"<{tag}>{render_runs(runs, ctx, block_id, in_link)}</{tag}>"

    match run:
        case Text(text):
            return esc(text)
        case MathInline(text, latex, asset):
            return _render_inline_math(text, latex, asset, ctx, block_id)
        case Italic(runs):
            return wrapped("i", runs)
        case Bold(runs):
            return wrapped("b", runs)
        case Sup(runs):
            return wrapped("sup", runs)
        case Sub(runs):
            return wrapped("sub", runs)
        case Link(href, runs):
            content = render_runs(runs, ctx, block_id, in_link=True)
            url = safe_href(href)
            if url is None:
                ctx.report("epub.link_dropped", f"dropped the link {href!r}", block_id)
            return _anchor(url, content, in_link)
        case Cite(target, runs):
            content = render_runs(runs, ctx, block_id, in_link=True)
            return _anchor(ctx.cite_hrefs.get(target), content, in_link)


def _render_inline_math(
    text: str, latex: str | None, asset: str | None, ctx: RenderContext, block_id: str | None
) -> str:
    if asset is not None:
        return _math_image(asset, latex or text, "math-inline", ctx)
    if latex:
        ctx.report(
            "epub.inline_math_text_fallback",
            f"inline math {latex!r} has no image, so it is shown as text",
            block_id,
        )
    return f'<span class="math">{esc(text or latex or "")}</span>'


def _math_image(asset: str, alt: str, css_class: str, ctx: RenderContext) -> str:
    """An image sized in em, so a formula grows with the reader's type size.

    `vertical-align` drops the image by its depth, which puts its baseline on the line's.
    """
    style = ""
    if box := ctx.math_boxes.get(asset):
        style = f' style="width:{box.width:.3f}em;vertical-align:{-box.depth:.3f}em"'
    src = esc(ctx.image_href(asset, True))
    return f'<img class="{css_class}" src="{src}" alt="{esc(alt)}"{style}/>'


def _anchor(url: str | None, content: str, in_link: bool) -> str:
    """Wrap `content` in a link, unless already inside one: an <a> can't contain an <a>."""
    if url is None or in_link:
        return content
    return f'<a href="{esc(url)}">{content}</a>'


def render_blocks(blocks: Sequence[Block], ctx: RenderContext) -> str:
    """Render blocks in order. Consecutive list items become one, possibly nested, list."""
    parts = []
    for is_list, group in groupby(blocks, key=lambda block: isinstance(block, ListItem)):
        if is_list:
            parts.append(_render_list(list(group), ctx))
        else:
            parts.extend(_render_block(block, ctx) for block in group)
    return "\n".join(parts)


def _render_block(block: Block, ctx: RenderContext) -> str:
    match block:
        case Heading():
            markup = _render_heading(block, ctx)
        case Paragraph():
            markup = _render_paragraph(block, ctx)
        case Equation():
            markup = _render_equation(block, ctx)
        case Figure():
            markup = _render_figure(block, ctx)
        case Table():
            markup = _render_table(block, ctx)
        case Reference():
            markup = _render_reference(block, ctx)
        case _:
            raise TypeError(f"can't render {type(block).__name__} on its own")
    return ctx.clean(markup, f"block {block.id!r}", block.id)


def _render_heading(block: Heading, ctx: RenderContext) -> str:
    tag = f"h{min(block.level, 6)}"
    number = f'<span class="number">{esc(block.number)}</span> ' if block.number else ""
    content = render_runs(block.runs, ctx, block.id)
    return f'<{tag} id="{ctx.anchors[block.id]}">{number}{content}</{tag}>'


def _render_paragraph(block: Paragraph, ctx: RenderContext) -> str:
    css_class = "" if block.role == "body" else f' class="{block.role}"'
    return f"<p{css_class}>{render_runs(block.runs, ctx, block.id)}</p>"


def _render_equation(block: Equation, ctx: RenderContext) -> str:
    number = ""
    if block.number:
        number = f' <span class="equation-number">({esc(block.number.strip("()"))})</span>'
    if block.asset is not None:
        alt = block.latex or block.alt or ""
        content = _math_image(block.asset, alt, "math-display", ctx)
    else:
        # The equation stage couldn't draw this one, and it must not disappear.
        ctx.report(
            "epub.equation_text_fallback",
            f"equation {block.id!r} has no image, so it is shown as text",
            block.id,
        )
        content = f'<code class="equation-text">{esc(block.alt or block.latex or "")}</code>'
    return f'<div class="equation" id="{ctx.anchors[block.id]}">{content}{number}</div>'


def _render_figure(block: Figure, ctx: RenderContext) -> str:
    title = f"Figure {block.number}"
    alt = block.alt or plain_text(block.caption) or title
    src = ctx.image_href(block.asset, False)
    return (
        f'<figure id="{ctx.anchors[block.id]}">'
        f'<img src="{esc(src)}" alt="{esc(alt)}"/>'
        f"<figcaption><b>{esc(title)}.</b> {render_runs(block.caption, ctx, block.id)}"
        "</figcaption></figure>"
    )


# A table with this many columns is set in a smaller size, so its numbers stay whole.
_WIDE_COLUMNS = 8
_VERY_WIDE_COLUMNS = 12


def _table_class(block: Table) -> str:
    columns = max((len(block.header), *map(len, block.rows)))
    if columns >= _VERY_WIDE_COLUMNS:
        return ' class="very-wide"'
    return ' class="wide"' if columns >= _WIDE_COLUMNS else ""


def _render_table(block: Table, ctx: RenderContext) -> str:
    def row(cells: Iterable[Runs], tag: str) -> str:
        rendered = (f"<{tag}>{render_runs(cell, ctx, block.id)}</{tag}>" for cell in cells)
        return f"<tr>{''.join(rendered)}</tr>"

    head = f"<thead>{row(block.header, 'th')}</thead>" if block.header else ""
    rows = "\n".join(row(cells, "td") for cells in block.rows)
    body = f"<tbody>\n{rows}\n</tbody>" if block.rows else ""
    table = f"<table{_table_class(block)}>{head}{body}</table>" if head or body else ""
    notes = ""
    if block.notes:
        notes = f'<p class="table-notes">{render_runs(block.notes, ctx, block.id)}</p>'
    return (
        f'<div class="table" id="{ctx.anchors[block.id]}">'
        f'<p class="caption"><b>Table {esc(block.number)}.</b> '
        f"{render_runs(block.caption, ctx, block.id)}</p>\n{table}{notes}</div>"
    )


def _render_reference(block: Reference, ctx: RenderContext) -> str:
    content = render_runs(block.runs, ctx, block.id)
    if block.doi and block.doi not in plain_text(block.runs):
        content += f' <a href="{esc(doi_url(block.doi))}">doi:{esc(block.doi)}</a>'
    return f'<p class="reference" id="{ctx.anchors[block.id]}">{content}</p>'


def _render_list(items: Sequence[ListItem], ctx: RenderContext) -> str:
    """Render list items, nesting by depth. A jump in depth nests one level, never more."""
    parts: list[str] = []
    open_lists: list[str] = []
    for item in items:
        tag = "ol" if item.ordered else "ul"
        level = min(max(item.depth, 0), len(open_lists)) + 1
        while len(open_lists) > level:
            parts.append(f"</li></{open_lists.pop()}>")
        if len(open_lists) == level and open_lists[-1] == tag:
            parts.append("</li>")
        else:
            if len(open_lists) == level:
                parts.append(f"</li></{open_lists.pop()}>")
            parts.append(f"<{tag}>")
            open_lists.append(tag)
        content = render_runs(item.runs, ctx, item.id)
        parts.append("<li>" + ctx.clean(content, f"block {item.id!r}", item.id))
    while open_lists:
        parts.append(f"</li></{open_lists.pop()}>")
    return "".join(parts)


def xhtml_page(title: str, body: str, language: str, body_attributes: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{esc(language)}" xml:lang="{esc(language)}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{esc(title)}</title>\n'
        '<link rel="stylesheet" type="text/css" href="kindle.css"/>\n</head>\n'
        f"<body{body_attributes}>\n{body}\n</body>\n</html>\n"
    )
