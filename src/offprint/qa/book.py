"""Read a finished EPUB as a reader would: the gate checks the file, not what was meant to be."""

import posixpath
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from offprint.qa.catalog import BY_ID
from offprint.qa.model import Finding, Outcome
from offprint.render.epub import BookLocation

_CONTAINER = "META-INF/container.xml"
_CONTAINER_NS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF_NS = "{http://www.idpf.org/2007/opf}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_XHTML_NS = "{http://www.w3.org/1999/xhtml}"
_MARKUP_SUFFIXES = (".xhtml", ".html", ".htm")
# Elements whose text doesn't run on into the next element's.
_SEPARATE = {
    "address", "blockquote", "br", "caption", "dd", "div", "dt", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "section", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "ul",
}  # fmt: skip


class BookError(ValueError):
    """The file isn't an EPUB that can be read."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Book:
    root: str
    """The folder inside the archive that hrefs start from, such as "OEBPS"."""
    spine: tuple[str, ...]
    """The reading order, as paths inside the archive."""
    markup: dict[str, bytes]
    """Every XHTML file in the archive, by path."""

    def name(self, path: str) -> str:
        """Return a path as `qa.json` gives it: relative to the OPF, like the book's own links."""
        return posixpath.relpath(path, self.root) if self.root else path


def _attribute(element: ElementTree.Element | None, name: str, what: str) -> str:
    value = None if element is None else element.get(name)
    if value is None:
        raise BookError(f"the book has no {what}")
    return value


def _read_package(path: Path) -> tuple[str, ElementTree.Element, dict[str, bytes]]:
    """Return the OPF's path and tree, and every XHTML file, from an EPUB."""
    try:
        with zipfile.ZipFile(path) as archive:
            container = ElementTree.fromstring(archive.read(_CONTAINER))
            rootfile = container.find(f".//{_CONTAINER_NS}rootfile")
            opf_path = _attribute(rootfile, "full-path", "package document")
            opf = ElementTree.fromstring(archive.read(opf_path))
            names = archive.namelist()
            markup = {n: archive.read(n) for n in names if n.lower().endswith(_MARKUP_SUFFIXES)}
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise BookError(f"can't read {path.name} as an EPUB: {error}") from error
    return opf_path, opf, markup


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageMeta:
    identifier: str
    title: str


def read_package_meta(path: Path) -> PackageMeta:
    """Read the book's `dc:identifier` and `dc:title`. Raises `BookError` if the file can't say."""
    _, opf, _ = _read_package(path)
    identifier = opf.findtext(f"{_OPF_NS}metadata/{_DC_NS}identifier")
    title = opf.findtext(f"{_OPF_NS}metadata/{_DC_NS}title")
    if not identifier or not title:
        raise BookError(f"{path.name} has no identifier or title in its package document")
    return PackageMeta(identifier=identifier.strip(), title=title.strip())


def read_book(path: Path) -> Book:
    """Open an EPUB and find its reading order. Raises `BookError` if the file can't say."""
    opf_path, opf, markup = _read_package(path)
    root = posixpath.dirname(opf_path)
    hrefs = {
        item.get("id"): item.get("href")
        for item in opf.iterfind(f"{_OPF_NS}manifest/{_OPF_NS}item")
    }
    spine = []
    for reference in opf.iterfind(f"{_OPF_NS}spine/{_OPF_NS}itemref"):
        href = hrefs.get(reference.get("idref"))
        if href is None:
            raise BookError(f"the spine names {reference.get('idref')!r}, which isn't in the book")
        spine.append(posixpath.join(root, href))
    return Book(root=root, spine=tuple(spine), markup=markup)


def _finding(message: str, name: str) -> Finding:
    return Finding(
        check="xhtml.wellformed",
        message=message,
        severity=BY_ID["xhtml.wellformed"].severity,
        location=BookLocation(name),
    )


def xhtml_wellformed(book: Book) -> Outcome:
    """Check that every XHTML file parses, and that the whole reading order is there."""
    found = []
    for path, data in book.markup.items():
        try:
            ElementTree.fromstring(data)
        except ElementTree.ParseError as error:
            found.append(_finding(f"{book.name(path)} isn't well-formed: {error}", book.name(path)))
    for path in book.spine:
        if path not in book.markup:
            found.append(_finding(f"{book.name(path)} is in the spine but not in the book", path))
    return Outcome(findings=tuple(found))


def _element_text(element: ElementTree.Element) -> Iterator[str]:
    yield element.text or ""
    for child in element:
        yield from _element_text(child)
        if child.tag.removeprefix(_XHTML_NS) in _SEPARATE:
            yield " "
        yield child.tail or ""


def reading_text(book: Book) -> Iterator[str]:
    """Yield the text of each file in reading order. Files that don't parse have none to give."""
    for path in book.spine:
        try:
            root = ElementTree.fromstring(book.markup.get(path, b""))
        except ElementTree.ParseError:
            continue
        body = root.find(f"{_XHTML_NS}body")
        if body is not None:
            yield "".join(_element_text(body))
