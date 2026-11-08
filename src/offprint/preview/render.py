"""Render Kindle-sized pages of an EPUB with Chromium, and write them with their manifest."""

import json
import os
import posixpath
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from string import Template

from PIL import Image
from playwright.sync_api import Page

from offprint.browser import chromium_page
from offprint.cover import font_faces
from offprint.preview.device import Device, load_device
from offprint.preview.frame import contact_sheet, eink, with_bezel
from offprint.preview.selection import (
    ChapterLayout,
    Flag,
    PreviewError,
    SelectedPage,
    automatic_selection,
    parse_page,
    read_flags,
    requested_selection,
)
from offprint.qa.book import Book, BookError, read_book

ASSETS = files("offprint.preview") / "assets"
MANIFEST_VERSION = 1
CONTACT_SHEET = "contact-sheet.png"
MANIFEST = "manifest.json"
_REPORT_MARK = "<!-- offprint preview -->"
# Laying out first is what makes the fonts in use start loading.
_FONTS_READY = "async () => { void document.body.offsetWidth; await document.fonts.ready; }"


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewOptions:
    pages: tuple[str, ...] = ()
    """`chapter:page` requests. Without any, the selection is automatic."""
    report: Path | None = None
    """A `qa.json`. By default, the one next to the EPUB, if there is one."""
    bezel: bool = False
    grayscale: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedPage:
    image: Path
    file: str
    page: int  # 1-based, as a reader counts.
    pages: int
    percent: int
    reasons: tuple[str, ...]
    checks: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewResult:
    outdir: Path
    pages: tuple[RenderedPage, ...]
    contact_sheet: Path
    manifest: Path
    report: Path | None
    """The `qa.json` used, if any."""
    unplaced: int
    """Findings with no place in the book, so no page to show."""
    overflowing_tables: tuple[str, ...] = ()
    """`file#id` of each table wider than the page."""


def reader_css(device: Device) -> str:
    """Build the stylesheet that paginates a chapter for this screen."""
    css = Template((ASSETS / "reader.css").read_text()).substitute(
        font_size=device.font_size,
        top_bar=device.top_bar,
        margin=device.margin,
        text_width=device.text_width,
        text_height=device.text_height,
        gap=2 * device.margin,
        image_height=device.text_height - device.image_room,
    )
    return f"{font_faces()}\n{css}"


def _open_chapter(page: Page, path: Path, css: str) -> None:
    """Open a chapter, paginated, with its images and fonts ready to measure."""
    page.goto(path.as_uri(), wait_until="load")
    page.add_style_tag(content=css)
    page.evaluate(_FONTS_READY)


def _measure(
    page: Page,
    root: Path,
    book: Book,
    css: str,
    flags: Sequence[Flag],
    device: Device,
) -> list[ChapterLayout]:
    script = (ASSETS / "measure.js").read_text()
    layouts = []
    for path in book.spine:
        file = book.name(path)
        fragments = sorted({f.fragment for f in flags if f.file == file and f.fragment})
        _open_chapter(page, root / path, css)
        measured = page.evaluate(script, {"fragments": fragments, "stride": device.width})
        measured["overflowing_tables"] = tuple(measured["overflowing_tables"])
        layouts.append(ChapterLayout(file=file, **measured))
    return layouts


def _percent(layouts: Sequence[ChapterLayout], file: str, index: int) -> int:
    total = sum(layout.pages for layout in layouts)
    before = 0
    for layout in layouts:
        if layout.file == file:
            break
        before += layout.pages
    return round(100 * (before + index + 1) / total)


def _finish(png: bytes, options: PreviewOptions) -> Image.Image:
    image = Image.open(BytesIO(png))
    if options.grayscale:
        image = eink(image)
    return with_bezel(image) if options.bezel else image.convert("RGB")


def _image_name(position: int, selected: SelectedPage) -> str:
    stem = posixpath.splitext(selected.file)[0].replace("/", "-")
    return f"{position:02}-{stem}-p{selected.page + 1}.png"


def _shoot(
    page: Page,
    root: Path,
    book: Book,
    css: str,
    layouts: Sequence[ChapterLayout],
    selected: Sequence[SelectedPage],
    outdir: Path,
    device: Device,
    options: PreviewOptions,
) -> list[RenderedPage]:
    script = (ASSETS / "show.js").read_text()
    by_file = {layout.file: layout for layout in layouts}
    paths = {book.name(path): path for path in book.spine}
    rendered = []
    current = None
    for position, item in enumerate(selected, start=1):
        if item.file != current:
            _open_chapter(page, root / paths[item.file], css)
            current = item.file
        layout = by_file[item.file]
        percent = _percent(layouts, item.file, item.page)
        page.evaluate(
            script,
            {
                "page": item.page,
                "stride": device.width,
                "margin": device.margin,
                "clock": device.clock,
                "left": layout.pages - item.page - 1,
                "percent": percent,
            },
        )
        image = outdir / _image_name(position, item)
        _finish(page.screenshot(type="png"), options).save(image)
        rendered.append(
            RenderedPage(
                image=image,
                file=item.file,
                page=item.page + 1,
                pages=layout.pages,
                percent=percent,
                reasons=item.reasons,
                checks=item.checks,
            )
        )
    return rendered


def _labels(rendered: RenderedPage) -> tuple[str, str]:
    where = f"{Path(rendered.file).stem} p. {rendered.page}/{rendered.pages}"
    reasons = f": {', '.join(rendered.reasons)}" if rendered.reasons else ""
    return f"{where}{reasons}", ", ".join(rendered.checks)


def _write_contact_sheet(pages: Sequence[RenderedPage], path: Path, device: Device) -> None:
    images = []
    for rendered in pages:
        with Image.open(rendered.image) as image:
            images.append((image.copy(), *_labels(rendered)))
    contact_sheet(images, device.contact_sheet).save(path)


def _manifest(
    epub: Path,
    pages: Sequence[RenderedPage],
    unplaced: int,
    overflowing: Sequence[str],
    device: Device,
) -> dict[str, object]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "epub": epub.name,
        "device": {"width": device.width, "height": device.height, "scale": device.scale},
        "contact_sheet": CONTACT_SHEET,
        "unplaced_findings": unplaced,
        "overflowing_tables": list(overflowing),
        "pages": [
            {
                "image": item.image.name,
                "file": item.file,
                "page": item.page,
                "pages": item.pages,
                "percent": item.percent,
                "reasons": list(item.reasons),
                "checks": list(item.checks),
            }
            for item in pages
        ],
    }


def report_section(result: PreviewResult, markdown: Path) -> str:
    """Write the part of `qa.md` that links the pages, with paths relative to it."""

    def link(path: Path) -> str:
        return Path(os.path.relpath(path, markdown.parent)).as_posix()

    lines = [
        "## Preview",
        "",
        "Kindle-sized renders, which only approximate a real Kindle.",
        "",
        f"[Contact sheet]({link(result.contact_sheet)})",
        "",
    ]
    for page in result.pages:
        label = ", ".join((*page.checks, *page.reasons))
        place = f"{page.file}, page {page.page} of {page.pages}"
        lines.append(f"- [{place}]({link(page.image)}): {label}")
    return "\n".join(lines) + "\n"


def link_report(result: PreviewResult) -> Path | None:
    """Add the preview to the `qa.md` next to its `qa.json`, replacing any from an earlier run."""
    markdown = result.report.with_suffix(".md") if result.report else None
    if markdown is None or not markdown.is_file():
        return None
    text = markdown.read_text(encoding="utf-8").split(_REPORT_MARK)[0].rstrip()
    section = report_section(result, markdown)
    markdown.write_text(f"{text}\n\n{_REPORT_MARK}\n\n{section}", encoding="utf-8")
    return markdown


def _report_path(epub: Path, options: PreviewOptions) -> Path | None:
    if options.report is not None:
        return options.report
    sibling = epub.with_suffix(".qa.json")
    return sibling if sibling.is_file() else None


def preview_epub(
    epub: Path, outdir: Path | None = None, options: PreviewOptions | None = None
) -> PreviewResult:
    """Render pages of `epub` into `outdir`, by default `<stem>.preview/` next to it."""
    options = options or PreviewOptions()
    outdir = outdir or epub.with_suffix(".preview")
    device = load_device()
    try:
        book = read_book(epub)
    except BookError as error:
        raise PreviewError(str(error)) from error

    report = None if options.pages else _report_path(epub, options)
    flags, unplaced = read_flags(report) if report else ((), 0)
    names = [book.name(path) for path in book.spine]
    requests = [parse_page(text, names) for text in options.pages]
    css = reader_css(device)

    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(epub) as archive:
        root = Path(folder)
        archive.extractall(root)
        outdir.mkdir(parents=True, exist_ok=True)
        with chromium_page(device.width, device.height, scale=device.scale) as page:
            layouts = _measure(page, root, book, css, flags, device)
            if requests:
                selected = requested_selection(requests, layouts)
            else:
                selected, lost = automatic_selection(layouts, flags)
                unplaced += len(lost)
            rendered = _shoot(page, root, book, css, layouts, selected, outdir, device, options)

    sheet = outdir / CONTACT_SHEET
    _write_contact_sheet(rendered, sheet, device)
    manifest = outdir / MANIFEST
    overflowing = tuple(
        f"{layout.file}#{table}" for layout in layouts for table in layout.overflowing_tables
    )
    data = _manifest(epub, rendered, unplaced, overflowing, device)
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return PreviewResult(
        outdir=outdir,
        pages=tuple(rendered),
        contact_sheet=sheet,
        manifest=manifest,
        report=report,
        unplaced=unplaced,
        overflowing_tables=overflowing,
    )
