"""The EPUB's package files: the OPF, the navigation document and the ZIP container."""

import io
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from offprint.ir import Meta
from offprint.render.epub.chapters import TocEntry
from offprint.render.epub.sanitize import strip_invalid_xml
from offprint.render.epub.xhtml import esc, xhtml_page

CONTENT_DIR = "OEBPS"
OPF_NAME = "content.opf"
NAV_NAME = "nav.xhtml"
COVER_PAGE_NAME = "cover.xhtml"
CSS_NAME = "kindle.css"

_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Lunaaaalj/offprint")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_CONTAINER_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{CONTENT_DIR}/{OPF_NAME}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@dataclass(frozen=True, slots=True)
class ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str | None = None


def book_identifier(meta: Meta, title: str) -> str:
    """Return the DOI or arXiv id, or else a UUID derived from the title, stable across runs."""
    if meta.doi:
        return f"doi:{meta.doi}"
    if meta.arxiv_id:
        return f"arxiv:{meta.arxiv_id}"
    authors = "|".join(author.name for author in meta.authors)
    return f"urn:uuid:{uuid.uuid5(_ID_NAMESPACE, f'{title}|{authors}|{meta.year}')}"


def render_opf(
    meta: Meta,
    title: str,
    language: str,
    modified: str,
    rights: str,
    manifest: Sequence[ManifestItem],
    spine: Sequence[str],
    cover_item: str | None,
) -> str:
    """Render the package document. `spine` lists manifest ids in reading order."""
    metadata = [
        f'<dc:identifier id="pub-id">{esc(book_identifier(meta, title))}</dc:identifier>',
        f"<dc:title>{esc(title)}</dc:title>",
        f"<dc:language>{esc(language)}</dc:language>",
    ]
    metadata.extend(_dc("creator", author.name) for author in meta.authors)
    if meta.year is not None:
        metadata.append(f"<dc:date>{meta.year:04}</dc:date>")
    metadata.append(_dc("publisher", meta.journal or ""))
    metadata.append(_dc("rights", rights))
    metadata.extend(_dc("subject", keyword) for keyword in meta.keywords)
    metadata.append(f'<meta property="dcterms:modified">{esc(modified)}</meta>')
    if cover_item:
        # Older Kindle software finds the cover through this EPUB 2 entry.
        metadata.append(f'<meta name="cover" content="{esc(cover_item)}"/>')

    items = []
    for item in manifest:
        properties = f' properties="{item.properties}"' if item.properties else ""
        items.append(
            f'<item id="{item.id}" href="{esc(item.href)}" '
            f'media-type="{item.media_type}"{properties}/>'
        )
    references = [f'<itemref idref="{item_id}"/>' for item_id in spine]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="pub-id" xml:lang="{esc(language)}">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(line for line in metadata if line)
        + "\n</metadata>\n<manifest>\n"
        + "\n".join(items)
        + "\n</manifest>\n<spine>\n"
        + "\n".join(references)
        + "\n</spine>\n</package>\n"
    )


def _dc(tag: str, value: str) -> str:
    """Return a Dublin Core element, or "" if it would be empty, which an OPF can't have."""
    return f"<dc:{tag}>{esc(value)}</dc:{tag}>" if strip_invalid_xml(value)[0].strip() else ""


def render_nav(
    title: str, toc: Sequence[TocEntry], language: str, cover_href: str | None, start_href: str
) -> str:
    """Render the navigation document: the TOC, plus landmarks for the reader's menus."""

    def entry(item: TocEntry) -> str:
        children = ""
        if item.children:
            children = "\n<ol>\n" + "\n".join(entry(child) for child in item.children) + "\n</ol>\n"
        return f'<li><a href="{esc(item.href)}">{esc(item.label)}</a>{children}</li>'

    landmarks = [f'<li><a epub:type="bodymatter" href="{esc(start_href)}">Start</a></li>']
    if cover_href:
        landmarks.insert(0, f'<li><a epub:type="cover" href="{esc(cover_href)}">Cover</a></li>')
    body = (
        '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n'
        + "\n".join(entry(item) for item in toc)
        + '\n</ol>\n</nav>\n<nav epub:type="landmarks" id="landmarks" hidden="hidden">\n<ol>\n'
        + "\n".join(landmarks)
        + "\n</ol>\n</nav>"
    )
    return xhtml_page(title, body, language)


def zip_epub(content: Mapping[str, bytes]) -> bytes:
    """Build the container. `content` maps paths inside `OEBPS/` to bytes, in writing order.

    Entries have a fixed timestamp, so the same input always gives the same bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:

        def add(name: str, data: bytes, method: int) -> None:
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = method
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)

        # EPUB requires this exact first entry: uncompressed, with no extra fields.
        add("mimetype", b"application/epub+zip", zipfile.ZIP_STORED)
        add("META-INF/container.xml", _CONTAINER_XML.encode(), zipfile.ZIP_DEFLATED)
        for name, data in content.items():
            add(f"{CONTENT_DIR}/{name}", data, zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
