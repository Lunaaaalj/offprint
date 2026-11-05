"""`render_epub`: assemble the chapters, images, cover and package files into an EPUB."""

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from offprint.ir import (
    Block,
    Document,
    Equation,
    Figure,
    Heading,
    Meta,
    Problem,
    Reference,
    Table,
    validate,
)
from offprint.render.epub.chapters import (
    FRONT_MATTER_FILE,
    Chapter,
    TocEntry,
    build_toc,
    split_chapters,
)
from offprint.render.epub.front_matter import license_text, render_front_matter
from offprint.render.epub.images import EpubImage, ImageError, prepare_image
from offprint.render.epub.package import (
    COVER_PAGE_NAME,
    CSS_NAME,
    NAV_NAME,
    OPF_NAME,
    ManifestItem,
    render_nav,
    render_opf,
    zip_epub,
)
from offprint.render.epub.sanitize import strip_invalid_xml
from offprint.render.epub.xhtml import RenderContext, esc, render_blocks, xhtml_page

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COVER_IMAGE_NAME = "images/cover.png"
_XHTML = "application/xhtml+xml"
_ANCHORED_BLOCKS = (Heading, Equation, Figure, Table, Reference)


class EpubRenderError(Exception):
    """The document can't be rendered, so no EPUB was written."""


@dataclass(frozen=True, slots=True)
class EpubOptions:
    # The IR doesn't record a language yet.
    language: str = "en"
    # Images wider than this are downscaled. None keeps every image at its size.
    max_image_width: int | None = 1600
    # `dcterms:modified`. By default it comes from the paper, so the output is reproducible.
    modified: datetime | None = None


@dataclass(frozen=True, slots=True)
class EpubResult:
    path: Path
    problems: tuple[Problem, ...]


class _ImageStore:
    """The book's images in first-use order, each prepared once per grayscale setting."""

    def __init__(self, doc: Document, max_width: int | None) -> None:
        self._assets = doc.assets
        self._max_width = max_width
        self._names: dict[tuple[str, bool], str] = {}
        self.images: dict[str, EpubImage] = {}
        self.converted: dict[str, str] = {}

    def href(self, asset_id: str, grayscale: bool) -> str:
        key = (asset_id, grayscale)
        if key not in self._names:
            try:
                image = prepare_image(
                    self._assets[asset_id], grayscale=grayscale, max_width=self._max_width
                )
            except ImageError as error:
                raise EpubRenderError(str(error)) from error
            # Asset ids aren't safe as file names, so the files are numbered.
            name = f"images/image-{len(self._names) + 1:03}.{image.extension}"
            self._names[key] = name
            self.images[name] = image
            if image.converted_from:
                self.converted[asset_id] = image.converted_from
        return self._names[key]


def render_epub(
    doc: Document,
    out_path: Path | str,
    cover: Path | str | bytes | None = None,
    options: EpubOptions | None = None,
) -> EpubResult:
    """Write `doc` to `out_path` as an EPUB 3 and return what had to change on the way.

    `cover` is a PNG, as a path or as bytes. Raises `EpubRenderError`, without writing anything,
    if the document is invalid, an image is unreadable or a part of the book is malformed.
    """
    options = options or EpubOptions()
    problems = validate(doc)
    if problems:
        summary = "; ".join(f"{problem.code}: {problem.message}" for problem in problems)
        raise EpubRenderError(f"the document is invalid: {summary}")
    cover_png = _load_cover(cover)

    leading, chapters = split_chapters(doc.blocks)
    anchors = _assign_anchors(doc.blocks)
    title = " ".join(strip_invalid_xml(doc.meta.title)[0].split()) or "Untitled"
    store = _ImageStore(doc, options.max_image_width)
    ctx = RenderContext(
        anchors=anchors,
        cite_hrefs=_cite_hrefs(leading, chapters, anchors),
        image_href=store.href,
    )

    def finish(name: str, markup: str) -> bytes:
        return _finish_part(name, markup, ctx)

    pages: dict[str, bytes] = {}
    if cover_png is not None:
        image = f'<img src="{_COVER_IMAGE_NAME}" alt="{esc(f"Cover: {title}")}"/>'
        attributes = ' class="cover" epub:type="cover"'
        cover_page = xhtml_page(title, image, options.language, attributes)
        pages[COVER_PAGE_NAME] = finish(COVER_PAGE_NAME, cover_page)
    front_body = render_front_matter(doc.meta, title, leading, doc.blocks, ctx)
    pages[FRONT_MATTER_FILE] = finish(
        FRONT_MATTER_FILE, xhtml_page(title, front_body, options.language)
    )
    for chapter in chapters:
        page = xhtml_page(chapter.label, render_blocks(chapter.blocks, ctx), options.language)
        pages[chapter.filename] = finish(chapter.filename, page)
    for asset_id, source_format in store.converted.items():
        ctx.report("epub.asset_converted", f"asset {asset_id!r} was {source_format}, now PNG")

    # Without any section the TOC would be empty, which EPUB doesn't allow.
    toc = build_toc(chapters, anchors) or (TocEntry(title, FRONT_MATTER_FILE),)
    start = chapters[0].filename if chapters else FRONT_MATTER_FILE
    cover_href = COVER_PAGE_NAME if cover_png is not None else None
    nav = render_nav(title, toc, options.language, cover_href, start)

    manifest = _manifest(chapters, store, cover_png is not None)
    opf = render_opf(
        doc.meta,
        title,
        options.language,
        _modified_timestamp(doc.meta, options),
        license_text(doc.meta),
        manifest,
        [item.id for item in manifest if item.media_type == _XHTML and item.properties != "nav"],
        "cover-image" if cover_png is not None else None,
    )

    content = {
        OPF_NAME: finish(OPF_NAME, opf),
        NAV_NAME: finish(NAV_NAME, nav),
        CSS_NAME: files("offprint.render.epub").joinpath(CSS_NAME).read_bytes(),
        **pages,
        **({_COVER_IMAGE_NAME: cover_png} if cover_png is not None else {}),
        **{name: image.data for name, image in store.images.items()},
    }
    data = zip_epub(content)

    # Written last and in one go, so a failure never leaves a partial EPUB behind.
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return EpubResult(path, tuple(ctx.problems))


def _load_cover(cover: Path | str | bytes | None) -> bytes | None:
    if cover is None:
        return None
    try:
        data = cover if isinstance(cover, bytes) else Path(cover).read_bytes()
    except OSError as error:
        raise EpubRenderError(f"can't read the cover: {error}") from error
    if not data.startswith(_PNG_SIGNATURE):
        raise EpubRenderError("the cover isn't a PNG")
    return data


def _assign_anchors(blocks: tuple[Block, ...]) -> dict[str, str]:
    """Number the anchors, because IR block ids aren't necessarily valid XML ids."""
    return {
        block.id: f"b{index}"
        for index, block in enumerate(blocks, start=1)
        if isinstance(block, _ANCHORED_BLOCKS)
    }


def _cite_hrefs(
    leading: tuple[Block, ...], chapters: tuple[Chapter, ...], anchors: dict[str, str]
) -> dict[str, str]:
    """Map each reference key to its location. If a key repeats, the first reference wins."""
    hrefs: dict[str, str] = {}
    parts = [(FRONT_MATTER_FILE, leading), *((c.filename, c.blocks) for c in chapters)]
    for filename, blocks in parts:
        for block in blocks:
            if isinstance(block, Reference) and block.key:
                hrefs.setdefault(block.key, f"{filename}#{anchors[block.id]}")
    return hrefs


def _finish_part(name: str, markup: str, ctx: RenderContext) -> bytes:
    """Apply the final safety net to a whole file, then prove the file is well-formed."""
    data = ctx.clean(markup, name).encode("utf-8")
    try:
        ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise EpubRenderError(f"{name} isn't well-formed XML: {error}") from error
    return data


def _manifest(
    chapters: tuple[Chapter, ...], store: _ImageStore, has_cover: bool
) -> list[ManifestItem]:
    """List the book's files. The order of the XHTML items is the reading order."""
    items = [
        ManifestItem("nav", NAV_NAME, _XHTML, "nav"),
        ManifestItem("css", CSS_NAME, "text/css"),
    ]
    if has_cover:
        items.append(ManifestItem("cover-page", COVER_PAGE_NAME, _XHTML))
        items.append(ManifestItem("cover-image", _COVER_IMAGE_NAME, "image/png", "cover-image"))
    items.append(ManifestItem("front-matter", FRONT_MATTER_FILE, _XHTML))
    items.extend(
        ManifestItem(f"chapter-{number}", chapter.filename, _XHTML)
        for number, chapter in enumerate(chapters, start=1)
    )
    items.extend(
        ManifestItem(f"image-{number}", name, image.media_type)
        for number, (name, image) in enumerate(store.images.items(), start=1)
    )
    return items


def _modified_timestamp(meta: Meta, options: EpubOptions) -> str:
    moment = options.modified or datetime(meta.year or 1970, 1, 1, tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
