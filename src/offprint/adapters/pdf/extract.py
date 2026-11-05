"""The only module that knows PyMuPDF: it reads a PDF into plain extraction data.

Text comes out with `TEXT_IGNORE_ACTUALTEXT`, because the alt-text on charts otherwise replaces the
visible glyphs. The alt-text itself is read separately from the structure tree.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from offprint.extraction import ExtractedTable, Line, Span, TableCell, TextBlock
from offprint.ir import Asset, BBox
from offprint.profiles import DocumentFacts
from offprint.profiles.schema import FontStyles

_TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_IGNORE_ACTUALTEXT
_FIGURE_TAG = re.compile(r"/Figure\s*<<\s*/MCID\s+(\d+)\s*>>\s*BDC")


@dataclass(frozen=True, slots=True, kw_only=True)
class PageData:
    number: int  # 1-based.
    width: float
    height: float
    blocks: tuple[TextBlock, ...]
    tables: tuple[ExtractedTable, ...]
    graphics: tuple[BBox, ...]
    """The boxes of drawn shapes and images."""
    figure_alts: tuple[str, ...]
    """Alt-text of the page's figures, in the order the page draws them."""


def open_pdf(path: Path) -> pymupdf.Document:
    return pymupdf.open(path)


def document_facts(doc: pymupdf.Document) -> DocumentFacts:
    """Collect what profile matching looks at. Subset prefixes are removed from font names."""
    fonts = {font[3].split("+")[-1] for page in doc for font in page.get_fonts()}
    metadata = doc.metadata or {}
    return DocumentFacts(
        producer=metadata.get("producer") or "",
        creator=metadata.get("creator") or "",
        fonts=frozenset(fonts),
        text=doc[0].get_text() if len(doc) else "",
    )


def citation_metadata(doc: pymupdf.Document) -> dict[str, str]:
    """Return the PDF's own metadata, as it stands."""
    return {key: value for key, value in (doc.metadata or {}).items() if isinstance(value, str)}


def _bbox(rect: object) -> BBox:
    x0, y0, x1, y1 = pymupdf.Rect(rect)
    return (float(x0), float(y0), float(x1), float(y1))


def _span(data: dict, page: int, styles: FontStyles) -> Span:
    font = data["font"]
    return Span(
        text=data["text"],
        bbox=_bbox(data["bbox"]),
        page=page,
        font=font,
        size=data["size"],
        bold=any(mark in font for mark in styles.bold),
        italic=any(mark in font for mark in styles.italic),
        superscript=bool(data["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT),
    )


def _block(data: dict, page: int, styles: FontStyles) -> TextBlock | None:
    lines = tuple(
        Line(
            spans=tuple(_span(span, page, styles) for span in line["spans"]),
            bbox=_bbox(line["bbox"]),
        )
        for line in data["lines"]
        if line["spans"]
    )
    return TextBlock(lines=lines, bbox=_bbox(data["bbox"]), page=page) if lines else None


def _tables(page: pymupdf.Page, number: int) -> tuple[ExtractedTable, ...]:
    tables = []
    for table in page.find_tables().tables:
        rows = tuple(
            tuple(
                None if cell is None else TableCell(spans=(), bbox=_bbox(cell))
                for cell in row.cells
            )
            for row in table.rows
        )
        tables.append(ExtractedTable(rows=rows, bbox=_bbox(table.bbox), page=number))
    return tuple(tables)


def _graphics(page: pymupdf.Page) -> tuple[BBox, ...]:
    drawings = [_bbox(item["rect"]) for item in page.get_drawings()]
    images = [_bbox(item["bbox"]) for item in page.get_image_info()]
    return tuple(drawings + images)


def _key(doc: pymupdf.Document, xref: int, key: str) -> tuple[str, str]:
    """Read a key of a PDF object. Real PDFs have dangling xrefs, which read as null."""
    try:
        return doc.xref_get_key(xref, key)
    except pymupdf.mupdf.FzErrorFormat:
        return ("null", "null")


def _structure_alts(doc: pymupdf.Document) -> dict[int, dict[int, str]]:
    """Return alt-text by page xref and marked-content id, from the structure tree's figures."""
    alts: dict[int, dict[int, str]] = {}
    for xref in range(1, doc.xref_length()):
        if _key(doc, xref, "S") != ("name", "/Figure"):
            continue
        kind, alt = _key(doc, xref, "ActualText")
        if kind != "string" or not alt.strip():
            continue
        content = _marked_content(doc, xref)
        if content is not None:
            page, mcid = content
            alts.setdefault(page, {})[mcid] = alt.strip()
    return alts


def _xref(reference: str) -> int:
    return int(reference.split()[0])


def _marked_content(doc: pymupdf.Document, xref: int) -> tuple[int, int] | None:
    """Return the page xref and marked-content id of a structure element."""
    kind, value = _key(doc, xref, "K")
    page_kind, page = _key(doc, xref, "Pg")
    if kind == "xref":
        target = _xref(value)
        kind, value = _key(doc, target, "MCID")
        target_kind, target_page = _key(doc, target, "Pg")
        if target_kind == "xref":
            page_kind, page = target_kind, target_page
    if kind != "int" or page_kind != "xref":
        return None
    return _xref(page), int(value)


def _page_alts(page: pymupdf.Page, alts: dict[int, str]) -> tuple[str, ...]:
    if not alts:
        return ()
    order = _FIGURE_TAG.findall(page.read_contents().decode("latin-1"))
    return tuple(alts[int(mcid)] for mcid in order if int(mcid) in alts)


def read_pages(doc: pymupdf.Document, styles: FontStyles) -> tuple[PageData, ...]:
    alts = _structure_alts(doc)
    pages = []
    for index, page in enumerate(doc):
        number = index + 1
        data = page.get_text("dict", flags=_TEXT_FLAGS)
        blocks = (_block(block, number, styles) for block in data["blocks"] if block["type"] == 0)
        pages.append(
            PageData(
                number=number,
                width=float(page.rect.width),
                height=float(page.rect.height),
                blocks=tuple(block for block in blocks if block is not None),
                tables=_tables(page, number),
                graphics=_graphics(page),
                figure_alts=_page_alts(page, alts.get(page.xref, {})),
            )
        )
    return tuple(pages)


def crop(
    doc: pymupdf.Document,
    *,
    page: int,
    bbox: BBox,
    zoom: float,
    grayscale: bool,
    asset_id: str,
) -> Asset:
    """Render part of a 1-based page to a PNG asset."""
    pixmap = doc[page - 1].get_pixmap(
        clip=pymupdf.Rect(bbox),
        matrix=pymupdf.Matrix(zoom, zoom),
        colorspace=pymupdf.csGRAY if grayscale else pymupdf.csRGB,
    )
    return Asset(
        id=asset_id,
        mime="image/png",
        bytes=pixmap.tobytes("png"),
        width=pixmap.width,
        height=pixmap.height,
    )
