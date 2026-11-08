"""The EPUB renderer, against a hand-built IR covering every block and run type."""

import io
import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from offprint.ir import (
    Asset,
    Author,
    Block,
    Bold,
    Cite,
    Document,
    Equation,
    Figure,
    Heading,
    Italic,
    License,
    Link,
    ListItem,
    MathBox,
    MathInline,
    Meta,
    Paragraph,
    Provenance,
    Reference,
    Sub,
    Sup,
    Table,
    Text,
)
from offprint.render.epub import EpubOptions, EpubRenderError, render_epub
from offprint.render.epub.images import prepare_image
from offprint.render.epub.package import book_identifier
from offprint.render.epub.sanitize import strip_invalid_xml
from offprint.render.epub.xhtml import safe_href

XHTML = "{http://www.w3.org/1999/xhtml}"
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
EPUB = "{http://www.idpf.org/2007/ops}"
HOSTILE = "a < b && c > d\x01 \"q\" 'r' \x0bend\x00"


def png(width: int = 8, height: int = 4, color: str = "red", mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


def jpeg(width: int = 8, height: int = 4) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buffer, "JPEG")
    return buffer.getvalue()


def asset(asset_id: str, data: bytes, mime: str = "image/png") -> Asset:
    return Asset(id=asset_id, mime=mime, bytes=data)


def doc_of(
    *blocks: Block, assets: tuple[Asset, ...] = (), meta: Meta | None = None, **fields: object
) -> Document:
    return Document(
        meta=meta or Meta(title="T"),
        blocks=blocks,
        assets={item.id: item for item in assets},
        provenance={block.id: Provenance(adapter="test") for block in blocks},
        **fields,
    )


def full_meta() -> Meta:
    return Meta(
        title="A <Study> & More",
        authors=(
            Author(name="Ada Lovelace", affiliations=("Analytical Engine Lab",)),
            Author(name="Alan Turing", affiliations=("Analytical Engine Lab",), corresponding=True),
            Author(name="Grace Hopper", affiliations=("Navy & Co",)),
        ),
        journal="Journal of <Tests>",
        year=2026,
        volume="9",
        article_id="1748985",
        doi="10.3389/frai.2026.1748985",
        license=License(spdx="CC-BY-4.0", holder="The Authors"),
        abstract=(Text("We "), Italic((Text("study"),)), Text(" things.")),
        keywords=("kindle", "epub & xml"),
    )


def full_doc() -> Document:
    """Every block and run type, with nesting, both kinds of equation and hostile text."""
    blocks: tuple[Block, ...] = (
        Paragraph(id="front-small", runs=(Text("Edited by nobody."),), role="small"),
        Heading(id="h1", level=1, number="1.", runs=(Text("Introduction"),)),
        Paragraph(
            id="p1",
            runs=(
                Text(HOSTILE),
                Italic((Bold((Sup((Text("nested"),)),)),)),
                Sub((Text("i"),)),
                Link("https://example.org/a b?x=1&y=2", (Italic((Text("site"),)),)),
                Cite("ref1", (Text("[1]"),)),
                Cite("missing", (Text("[2]"),)),
                MathInline("x < y", latex=r"x < y"),
            ),
        ),
        ListItem(id="l1", runs=(Text("one"),)),
        ListItem(id="l2", runs=(Text("one.a"),), depth=1, ordered=True),
        ListItem(id="l3", runs=(Text("two"),)),
        Heading(id="h1.1", level=2, number="1.1", runs=(Text("Back"), Italic((Text("ground"),)))),
        Heading(id="h1.1.1", level=3, runs=(Text("Too deep for the TOC"),)),
        Equation(id="e1", alt="E = mc^2", number="1", asset="eq"),
        Equation(id="e2", alt="", number="2", latex=r"\frac{a}{b} < c"),
        Equation(id="e3", alt="a+b", latex="a+b", asset="eq"),
        Figure(
            id="f1",
            number="1",
            asset="fig",
            caption=(Text("A "), Bold((Text("chart"),)), Text(" & more.")),
            alt="Bars <rising>",
        ),
        Table(
            id="t1",
            number="1",
            caption=(Text("Results"),),
            header=((Text("Model"),), (Italic((Text("n"),)),)),
            rows=(((Text("A<B"),), (Text("1"),)), ((Text("C"),), ())),
            notes=(Text("n: sample size."),),
        ),
        Heading(id="h2", level=1, number="2.", runs=(Text("References"),)),
        Reference(id="r1", runs=(Text("Doe (2020)."),), key="ref1", doi="10.1000/xyz<1>"),
        Reference(id="r2", runs=(Text("Roe. doi:10.1000/abc"),), doi="10.1000/abc"),
    )
    return doc_of(
        *blocks,
        assets=(asset("eq", png()), asset("fig", jpeg(), "image/jpeg")),
        meta=full_meta(),
    )


class Book:
    """An EPUB opened for inspection."""

    def __init__(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            self.infos = archive.infolist()
            self.files = {info.filename: archive.read(info) for info in self.infos}

    def text(self, name: str) -> str:
        return self.files[f"OEBPS/{name}"].decode("utf-8")

    def xml(self, name: str) -> ElementTree.Element:
        return ElementTree.fromstring(self.files[f"OEBPS/{name}"])

    @property
    def xhtml_names(self) -> list[str]:
        return [name for name in self.files if name.endswith(".xhtml")]


def render(tmp_path: Path, doc: Document, **kwargs: object) -> Book:
    return Book(render_epub(doc, tmp_path / "book.epub", **kwargs).path)


def text_of(element: ElementTree.Element) -> str:
    return "".join(element.itertext())


def find(root: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return list(root.iter(f"{XHTML}{tag}"))


def test_every_part_is_well_formed(tmp_path):
    book = render(tmp_path, full_doc())
    assert len(book.xhtml_names) == 4
    for name, data in book.files.items():
        if name.endswith((".xhtml", ".opf", ".xml")):
            ElementTree.fromstring(data)


def test_container_layout(tmp_path):
    book = render(tmp_path, full_doc())
    first = book.infos[0]
    assert first.filename == "mimetype"
    assert first.compress_type == zipfile.ZIP_STORED
    assert first.extra == b""
    assert book.files["mimetype"] == b"application/epub+zip"
    assert b"OEBPS/content.opf" in book.files["META-INF/container.xml"]


def test_rendering_is_deterministic(tmp_path):
    first = render_epub(full_doc(), tmp_path / "a.epub").path.read_bytes()
    second = render_epub(full_doc(), tmp_path / "b.epub").path.read_bytes()
    assert first == second


def test_one_chapter_per_top_level_heading(tmp_path):
    book = render(tmp_path, full_doc())
    assert text_of(find(book.xml("chapter-01.xhtml"), "h1")[0]) == "1. Introduction"
    assert text_of(find(book.xml("chapter-02.xhtml"), "h1")[0]) == "2. References"
    spine = [item.get("idref") for item in book.xml("content.opf").iter(f"{OPF}itemref")]
    assert spine == ["front-matter", "chapter-1", "chapter-2"]


def test_front_matter_comes_from_meta_and_leading_blocks(tmp_path):
    book = render(tmp_path, full_doc())
    body = book.xml("front-matter.xhtml")
    text = text_of(body)
    assert text_of(find(body, "h1")[0]) == "A <Study> & More"
    assert "Ada Lovelace1, Alan Turing1, Grace Hopper2" in text
    assert text.count("Analytical Engine Lab") == 1
    assert "Navy & Co" in text
    assert "We study things." in text
    assert "kindle, epub & xml" in text
    assert "Journal of <Tests> (2026) 9:1748985 doi:10.3389/frai.2026.1748985" in text
    assert "© The Authors. Licensed under CC-BY-4.0." in text
    assert "Edited by nobody." in text


def test_abstract_blocks_replace_the_meta_abstract(tmp_path):
    meta = replace(full_meta(), abstract=(Text("from meta"),))
    paragraph = Paragraph(id="a", runs=(Text("from blocks"),), role="abstract")
    text = text_of(render(tmp_path, doc_of(paragraph, meta=meta)).xml("front-matter.xhtml"))
    assert "from blocks" in text
    assert "from meta" not in text


def test_a_meta_paragraph_replaces_the_citation_line(tmp_path):
    paragraph = Paragraph(id="m", runs=(Text("Cite as: somebody."),), role="meta")
    book = render(tmp_path, doc_of(paragraph, meta=full_meta()))
    assert 'class="meta"' in book.text("front-matter.xhtml")
    assert 'class="citation"' not in book.text("front-matter.xhtml")


def test_nav_is_two_levels_deep(tmp_path):
    nav = render(tmp_path, full_doc()).xml("nav.xhtml")
    toc = next(n for n in find(nav, "nav") if n.get(f"{EPUB}type") == "toc")
    top = toc.find(f"{XHTML}ol").findall(f"{XHTML}li")
    labels = [item.find(f"{XHTML}a").text for item in top]
    assert labels == ["1. Introduction", "2. References"]
    children = top[0].find(f"{XHTML}ol").findall(f"{XHTML}li")
    assert [item.find(f"{XHTML}a").text for item in children] == ["1.1 Background"]
    assert top[1].find(f"{XHTML}ol") is None
    assert "Too deep" not in text_of(toc)


def test_nav_links_point_at_existing_anchors(tmp_path):
    book = render(tmp_path, full_doc())
    nav = book.xml("nav.xhtml")
    targets = [a.get("href") for a in find(nav, "a")]
    assert targets
    for target in targets:
        filename, _, fragment = target.partition("#")
        page = book.xml(filename)
        if fragment:
            assert any(element.get("id") == fragment for element in page.iter()), target


def test_toc_lists_every_section_and_subsection(tmp_path):
    blocks: list[Block] = []
    for section in range(1, 16):
        blocks.append(Heading(id=f"s{section}", level=1, runs=(Text(f"Section {section}"),)))
        blocks.append(Heading(id=f"s{section}.1", level=2, runs=(Text("Sub"),)))
    nav = render(tmp_path, doc_of(*blocks)).xml("nav.xhtml")
    toc = find(nav, "nav")[0]
    top = toc.find(f"{XHTML}ol").findall(f"{XHTML}li")
    assert len(top) == 15
    assert all(len(item.find(f"{XHTML}ol").findall(f"{XHTML}li")) == 1 for item in top)


def test_a_paper_without_sections_still_has_a_toc(tmp_path):
    book = render(tmp_path, doc_of(Paragraph(id="p", runs=(Text("x"),))))
    assert [a.get("href") for a in find(find(book.xml("nav.xhtml"), "nav")[0], "a")] == [
        "front-matter.xhtml"
    ]


def test_an_empty_heading_still_gets_a_toc_label(tmp_path):
    nav = render(tmp_path, doc_of(Heading(id="h", level=1, runs=()))).xml("nav.xhtml")
    assert find(nav, "a")[0].text == "Section 1"


def test_opf_metadata(tmp_path):
    opf = render(tmp_path, full_doc()).xml("content.opf")
    metadata = opf.find(f"{OPF}metadata")

    def values(tag: str) -> list[str]:
        return [element.text for element in metadata.findall(f"{DC}{tag}")]

    assert values("title") == ["A <Study> & More"]
    assert values("creator") == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert values("date") == ["2026"]
    assert values("publisher") == ["Journal of <Tests>"]
    assert values("identifier") == ["doi:10.3389/frai.2026.1748985"]
    assert values("rights") == ["© The Authors. Licensed under CC-BY-4.0."]
    assert values("language") == ["en"]
    assert values("subject") == ["kindle", "epub & xml"]
    modified = metadata.find(f"{OPF}meta[@property='dcterms:modified']")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", modified.text)


def test_identifier_falls_back_to_arxiv_then_to_a_stable_uuid(tmp_path):
    def identifier(meta: Meta) -> str:
        opf = render(tmp_path, doc_of(meta=meta)).xml("content.opf")
        return opf.find(f"{OPF}metadata/{DC}identifier").text

    assert identifier(Meta(title="T", arxiv_id="2401.01234")) == "arxiv:2401.01234"
    derived = identifier(Meta(title="T"))
    assert derived.startswith("urn:uuid:")
    assert derived == identifier(Meta(title="T"))
    assert derived != identifier(Meta(title="U"))


def test_language_and_modified_options(tmp_path):
    options = EpubOptions(language="es", modified=datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC))
    book = render(tmp_path, doc_of(), options=options)
    assert 'lang="es"' in book.text("front-matter.xhtml")
    assert "2026-03-04T05:06:07Z" in book.text("content.opf")


def test_runs_nest(tmp_path):
    page = render(tmp_path, full_doc()).text("chapter-01.xhtml")
    assert "<i><b><sup>nested</sup></b></i>" in page
    assert "<sub>i</sub>" in page
    assert '<span class="math">x &lt; y</span>' in page


def test_hostile_text_is_escaped_and_control_characters_stripped(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-01.xhtml")
    assert "a < b && c > d \"q\" 'r' end" in text_of(root)


def test_links_are_encoded(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-01.xhtml")
    links = find(root, "a")
    assert links[0].get("href") == "https://example.org/a%20b?x=1&y=2"
    assert text_of(links[0]) == "site"


def test_cite_links_to_its_reference_across_chapters(tmp_path):
    book = render(tmp_path, full_doc())
    links = {text_of(a): a.get("href") for a in find(book.xml("chapter-01.xhtml"), "a")}
    filename, _, fragment = links["[1]"].partition("#")
    assert filename == "chapter-02.xhtml"
    target = next(e for e in book.xml(filename).iter() if e.get("id") == fragment)
    assert text_of(target).startswith("Doe (2020).")
    assert "[2]" not in links  # no matching reference, so it stays plain text
    assert "[2]" in text_of(book.xml("chapter-01.xhtml"))


def test_reference_gets_a_doi_link_unless_its_text_has_one(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-02.xhtml")
    links = find(root, "a")
    assert len(links) == 1
    assert links[0].get("href") == "https://doi.org/10.1000/xyz%3C1%3E"
    assert text_of(links[0]) == "doi:10.1000/xyz<1>"


def test_links_never_nest(tmp_path):
    inner = Cite("k", (Link("https://b.example", (Text("inner"),)),))
    blocks = (
        Paragraph(id="p", runs=(Link("https://a.example", (inner,)),)),
        Reference(id="r", runs=(Text("ref"),), key="k"),
    )
    root = render(tmp_path, doc_of(*blocks)).xml("front-matter.xhtml")
    outer = next(a for a in find(root, "a") if a.get("href") == "https://a.example")
    assert list(outer.iter(f"{XHTML}a")) == [outer]
    assert text_of(outer) == "inner"


@pytest.mark.parametrize(
    "href",
    ["javascript:alert(1)", "", "chapter-99.xhtml#nowhere", "http://", "http://[bad", "http://a:b"],
)
def test_unusable_links_keep_their_text_and_are_reported(tmp_path, href):
    doc = doc_of(Paragraph(id="p", runs=(Link(href, (Text("label"),)),)))
    result = render_epub(doc, tmp_path / "book.epub")
    root = Book(result.path).xml("front-matter.xhtml")
    assert find(root, "a") == []
    assert "label" in text_of(root)
    assert [(p.code, p.block_id) for p in result.problems] == [("epub.link_dropped", "p")]


def test_safe_href_keeps_good_urls():
    assert safe_href("https://a.example/x?y=1#z") == "https://a.example/x?y=1#z"
    assert safe_href("mailto:a@b.example") == "mailto:a@b.example"


def test_paragraph_roles_become_classes(tmp_path):
    blocks = [Paragraph(id=role, runs=(Text("x"),), role=role) for role in ("small", "meta")]
    blocks.append(Paragraph(id="body", runs=(Text("y"),)))
    page = render(tmp_path, doc_of(*blocks)).text("front-matter.xhtml")
    assert '<p class="small">x</p>' in page
    assert '<p class="meta">x</p>' in page
    assert "<p>y</p>" in page


def test_lists_nest_validly(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-01.xhtml")
    outer = find(root, "ul")
    assert len(outer) == 1
    items = outer[0].findall(f"{XHTML}li")
    assert [item.text for item in items] == ["one", "two"]
    assert items[0].find(f"{XHTML}ol/{XHTML}li").text == "one.a"


def test_list_type_changes_and_depth_jumps(tmp_path):
    items = (
        ListItem(id="a", runs=(Text("a"),), depth=3),  # nothing to nest in yet
        ListItem(id="b", runs=(Text("b"),), depth=5),
        ListItem(id="c", runs=(Text("c"),), depth=1, ordered=True),  # type change, same level
        ListItem(id="d", runs=(Text("d"),), ordered=True),  # type change, shallower
    )
    root = render(tmp_path, doc_of(*items)).xml("front-matter.xhtml")
    lists = [e.tag.removeprefix(XHTML) for e in root.iter() if e.tag.endswith(("}ul", "}ol"))]
    assert lists == ["ul", "ul", "ol", "ol"]
    assert all(child.tag == f"{XHTML}li" for e in find(root, "ul") for child in e)
    assert [li.text for li in find(root, "li")] == ["a", "b", "c", "d"]


def test_equation_with_only_latex_stays_visible_and_is_logged(tmp_path, caplog):
    doc = doc_of(Equation(id="e", alt="", number="3", latex=r"\frac{a}{b} < c"))
    with caplog.at_level(logging.WARNING, logger="offprint.render.epub"):
        result = render_epub(doc, tmp_path / "book.epub")
    root = Book(result.path).xml("front-matter.xhtml")
    assert r"\frac{a}{b} < c" in text_of(root)
    assert "(3)" in text_of(root)
    assert find(root, "img") == []
    assert [(p.code, p.block_id) for p in result.problems] == [("epub.equation_text_fallback", "e")]
    assert "epub.equation_text_fallback" in caplog.text


def test_equation_text_fallback_prefers_alt(tmp_path):
    doc = doc_of(Equation(id="e", alt="a over b", latex=r"\frac{a}{b}"))
    assert "a over b" in text_of(render(tmp_path, doc).xml("front-matter.xhtml"))


def test_equation_with_only_an_asset_is_an_image(tmp_path):
    doc = doc_of(Equation(id="e", alt="", asset="a"), assets=(asset("a", png()),))
    result = render_epub(doc, tmp_path / "book.epub")
    img = find(Book(result.path).xml("front-matter.xhtml"), "img")[0]
    assert img.get("alt") == ""
    assert result.problems == ()


def test_equation_image_alt_falls_back_to_latex(tmp_path):
    doc = doc_of(Equation(id="e", alt="", latex="a+b", asset="a"), assets=(asset("a", png()),))
    assert find(render(tmp_path, doc).xml("front-matter.xhtml"), "img")[0].get("alt") == "a+b"


def test_figure_markup(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-01.xhtml")
    figure = find(root, "figure")[0]
    img = figure.find(f"{XHTML}img")
    assert img.get("alt") == "Bars <rising>"
    assert text_of(figure.find(f"{XHTML}figcaption")) == "Figure 1. A chart & more."


def test_figure_alt_falls_back_to_caption_then_number(tmp_path):
    doc = doc_of(
        Figure(id="f1", number="1", asset="a", caption=(Text("Cap"),)),
        Figure(id="f2", number="S2", asset="a", caption=()),
        assets=(asset("a", png()),),
    )
    alts = [i.get("alt") for i in find(render(tmp_path, doc).xml("front-matter.xhtml"), "img")]
    assert alts == ["Cap", "Figure S2"]


def test_table_markup(tmp_path):
    root = render(tmp_path, full_doc()).xml("chapter-01.xhtml")
    table = find(root, "table")[0]
    assert [text_of(th) for th in table.iter(f"{XHTML}th")] == ["Model", "n"]
    rows = table.find(f"{XHTML}tbody").findall(f"{XHTML}tr")
    assert [[text_of(td) for td in row] for row in rows] == [["A<B", "1"], ["C", ""]]
    assert "Table 1. Results" in text_of(root)
    assert "n: sample size." in text_of(root)


@pytest.mark.parametrize(
    ("columns", "expected"), [(2, None), (7, None), (8, "wide"), (11, "wide"), (12, "very-wide")]
)
def test_a_wide_table_gets_a_class_from_its_column_count(tmp_path, columns, expected):
    cells = tuple((Text(str(n)),) for n in range(columns))
    table = Table(id="t", number="1", caption=(), header=cells, rows=(cells,))
    root = render(tmp_path, doc_of(table)).xml("front-matter.xhtml")
    assert find(root, "table")[0].get("class") == expected


def byline(tmp_path, *authors):
    doc = doc_of(meta=Meta(title="T", authors=authors))
    body = render(tmp_path, doc).xml("front-matter.xhtml")
    authors_line = next(p for p in find(body, "p") if p.get("class") == "authors")
    affiliations = [p for p in find(body, "p") if p.get("class") == "affiliation"]
    return authors_line, affiliations


def test_with_several_affiliations_each_is_numbered_and_each_author_shows_theirs(tmp_path):
    line, affiliations = byline(
        tmp_path,
        Author(name="A", affiliations=("Lab X",)),
        Author(name="B", affiliations=("Lab X", "Lab Y")),
    )

    assert [(sup.text or "") for sup in line.iter(f"{XHTML}sup")] == ["1", "1,2"]
    assert text_of(line) == "A1, B1,2"
    assert [text_of(p) for p in affiliations] == ["1 Lab X", "2 Lab Y"]


def test_with_one_affiliation_nothing_is_numbered(tmp_path):
    line, affiliations = byline(
        tmp_path,
        Author(name="A", affiliations=("Lab X",)),
        Author(name="B", affiliations=("Lab X",)),
    )

    assert text_of(line) == "A, B"
    assert [text_of(p) for p in affiliations] == ["Lab X"]


def test_markers_follow_the_name_but_stay_out_of_the_creator(tmp_path):
    doc = doc_of(
        meta=Meta(
            title="T",
            authors=(Author(name="Aidan Gomez", markers=("∗", "†")), Author(name="B")),
        )
    )
    book = render(tmp_path, doc)

    line = next(p for p in find(book.xml("front-matter.xhtml"), "p") if p.get("class") == "authors")
    creators = [e.text for e in book.xml("content.opf").iter(f"{DC}creator")]

    assert text_of(line) == "Aidan Gomez∗,†, B"
    assert creators == ["Aidan Gomez", "B"]


def test_an_author_with_no_affiliation_shows_no_number(tmp_path):
    line, _ = byline(
        tmp_path,
        Author(name="A", affiliations=("Lab X",)),
        Author(name="B"),
        Author(name="C", affiliations=("Lab Y",)),
    )

    assert text_of(line) == "A1, B, C2"


def test_empty_table_has_no_empty_sections(tmp_path):
    doc = doc_of(Table(id="t", number="1", caption=(), header=(), rows=()))
    assert find(render(tmp_path, doc).xml("front-matter.xhtml"), "table") == []


def test_headings_past_h6_are_clamped(tmp_path):
    blocks = [Heading(id=f"h{n}", level=n, runs=(Text(str(n)),)) for n in range(1, 8)]
    page = render(tmp_path, doc_of(*blocks)).text("chapter-01.xhtml")
    assert page.count("<h6") == 2
    assert "<h7" not in page


def test_block_ids_never_reach_the_output(tmp_path):
    doc = doc_of(Heading(id='bad id "<', level=1, runs=(Text("x"),)))
    page = render(tmp_path, doc).xml("chapter-01.xhtml")
    assert find(page, "h1")[0].get("id") == "b1"


# Images


def manifest_types(book: Book) -> dict[str, str]:
    items = book.xml("content.opf").iter(f"{OPF}item")
    return {item.get("href"): item.get("media-type") for item in items}


def stored_images(book: Book) -> dict[str, Image.Image]:
    return {
        name.removeprefix("OEBPS/"): Image.open(io.BytesIO(data))
        for name, data in book.files.items()
        if "/images/" in name
    }


def test_figures_keep_colour_and_equations_turn_gray(tmp_path):
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        Equation(id="e", alt="x", asset="a"),
        assets=(asset("a", png(color="red")),),
    )
    images = stored_images(render(tmp_path, doc))
    assert sorted(image.mode for image in images.values()) == ["L", "RGB"]


def test_an_image_used_twice_is_stored_once(tmp_path):
    doc = doc_of(
        Figure(id="f1", number="1", asset="a", caption=()),
        Figure(id="f2", number="2", asset="a", caption=()),
        assets=(asset("a", png()),),
    )
    assert len(stored_images(render(tmp_path, doc))) == 1


def test_unused_assets_are_left_out(tmp_path):
    assert stored_images(render(tmp_path, doc_of(assets=(asset("a", png()),)))) == {}


def test_images_are_declared_with_their_real_type(tmp_path):
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        assets=(asset("a", jpeg(), "image/png"),),  # the IR's mime is wrong
    )
    book = render(tmp_path, doc)
    assert manifest_types(book)["images/image-001.jpg"] == "image/jpeg"


def test_every_stored_image_is_in_the_manifest_with_a_real_file(tmp_path):
    book = render(tmp_path, full_doc())
    hrefs = manifest_types(book)
    for href in hrefs:
        assert f"OEBPS/{href}" in book.files
    for name in book.files:
        if name.startswith("OEBPS/") and not name.endswith(".opf"):
            assert name.removeprefix("OEBPS/") in hrefs


def test_wide_images_are_downscaled_keeping_their_shape(tmp_path):
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        assets=(asset("a", png(width=2000, height=1000)),),
    )
    image = next(iter(stored_images(render(tmp_path, doc)).values()))
    assert image.size == (1600, 800)


def test_downscaling_limit_is_an_option(tmp_path):
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        assets=(asset("a", png(width=2000, height=1000)),),
    )
    small = render(tmp_path, doc, options=EpubOptions(max_image_width=100))
    assert next(iter(stored_images(small).values())).size == (100, 50)
    full = render(tmp_path, doc, options=EpubOptions(max_image_width=None))
    assert next(iter(stored_images(full).values())).size == (2000, 1000)


def test_small_images_keep_their_exact_bytes():
    data = png()
    assert prepare_image(asset("a", data), grayscale=False, max_width=1600).data == data
    gray = png(mode="L", color="white")
    assert prepare_image(asset("a", gray), grayscale=True, max_width=1600).data == gray


def test_transparency_survives_grayscale():
    data = png(mode="RGBA", color="#ff000080")
    prepared = prepare_image(asset("a", data), grayscale=True, max_width=None)
    assert Image.open(io.BytesIO(prepared.data)).mode == "LA"


def test_palette_images_can_be_downscaled():
    buffer = io.BytesIO()
    Image.new("P", (20, 10)).save(buffer, "PNG")
    prepared = prepare_image(asset("a", buffer.getvalue()), grayscale=False, max_width=10)
    assert Image.open(io.BytesIO(prepared.data)).size == (10, 5)


def test_other_formats_become_png_and_are_reported(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buffer, "GIF")
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        assets=(asset("a", buffer.getvalue(), "image/gif"),),
    )
    result = render_epub(doc, tmp_path / "book.epub")
    assert "images/image-001.png" in manifest_types(Book(result.path))
    assert [p.code for p in result.problems] == ["epub.asset_converted"]


def test_unreadable_image_fails_without_writing(tmp_path):
    doc = doc_of(
        Figure(id="f", number="1", asset="a", caption=()),
        assets=(asset("a", b"not an image"),),
    )
    with pytest.raises(EpubRenderError, match="isn't a readable image"):
        render_epub(doc, tmp_path / "book.epub")
    assert not (tmp_path / "book.epub").exists()


# Cover


def test_cover_from_bytes(tmp_path):
    book = render(tmp_path, full_doc(), cover=png(16, 24))
    opf = book.xml("content.opf")
    items = {item.get("id"): item for item in opf.iter(f"{OPF}item")}
    assert items["cover-image"].get("properties") == "cover-image"
    assert book.files["OEBPS/images/cover.png"] == png(16, 24)
    assert find(book.xml("cover.xhtml"), "img")[0].get("src") == "images/cover.png"
    spine = [item.get("idref") for item in opf.iter(f"{OPF}itemref")]
    assert spine[0] == "cover-page"
    assert opf.find(f"{OPF}metadata/{OPF}meta[@name='cover']").get("content") == "cover-image"
    assert any(a.get(f"{EPUB}type") == "cover" for a in find(book.xml("nav.xhtml"), "a"))


def test_cover_from_a_path(tmp_path):
    path = tmp_path / "cover.png"
    path.write_bytes(png())
    assert "OEBPS/images/cover.png" in render(tmp_path, doc_of(), cover=path).files
    assert "OEBPS/images/cover.png" in render(tmp_path, doc_of(), cover=str(path)).files


def test_no_cover_means_no_cover_files(tmp_path):
    book = render(tmp_path, doc_of())
    assert "OEBPS/cover.xhtml" not in book.files
    assert "cover" not in book.text("content.opf")


def test_cover_must_be_a_png(tmp_path):
    with pytest.raises(EpubRenderError, match="isn't a PNG"):
        render_epub(doc_of(), tmp_path / "book.epub", cover=jpeg())
    with pytest.raises(EpubRenderError, match="can't read the cover"):
        render_epub(doc_of(), tmp_path / "book.epub", cover=tmp_path / "missing.png")
    assert not (tmp_path / "book.epub").exists()


# Stylesheet


def test_stylesheet_is_packaged_and_linked(tmp_path):
    book = render(tmp_path, full_doc())
    css = book.text("kindle.css")
    assert "table-layout: auto" in css
    assert "hyphens: manual" in css
    assert "text-indent: -1.2em" in css
    assert 'href="kindle.css"' in book.text("chapter-01.xhtml")
    assert manifest_types(book)["kindle.css"] == "text/css"


# Invalid characters: the bug that once silently lost a whole chapter.


@pytest.mark.parametrize(
    "char", ["\x00", "\x01", "\x0b", "\x0c", "\x1f", "\x7f", "\x85", "\ud800", "\ufffe", "\uffff"]
)
def test_strip_invalid_xml_removes(char):
    assert strip_invalid_xml(f"a{char}b") == ("ab", [f"U+{ord(char):04X}"])


def test_strip_invalid_xml_removes_supplementary_noncharacters():
    assert strip_invalid_xml("a\U0001fffeb")[0] == "ab"


def test_strip_invalid_xml_keeps_valid_text():
    text = "tab\t nl\n cr\r é Ş ﬁ 😀 \ue000 \ufffd"
    assert strip_invalid_xml(text) == (text, [])


def test_stripping_is_logged_and_reported_against_the_block(tmp_path, caplog):
    doc = doc_of(
        Heading(id="h", level=1, runs=(Text("Intro"),)),
        Paragraph(id="p", runs=(Text("a\x01b\x02c\x01"),)),
    )
    with caplog.at_level(logging.WARNING, logger="offprint.render.epub"):
        result = render_epub(doc, tmp_path / "book.epub")
    assert [(p.code, p.block_id) for p in result.problems] == [("epub.invalid_xml_chars", "p")]
    assert "3 invalid character(s) (U+0001, U+0002)" in result.problems[0].message
    assert "epub.invalid_xml_chars" in caplog.text
    assert "abc" in text_of(Book(result.path).xml("chapter-01.xhtml"))


def test_clean_text_reports_nothing(tmp_path):
    doc = doc_of(Paragraph(id="p", runs=(Text("clean"),)))
    assert render_epub(doc, tmp_path / "book.epub").problems == ()


def test_control_characters_in_metadata_are_stripped_everywhere(tmp_path):
    meta = Meta(
        title="Ti\x01tle",
        authors=(Author(name="An\x02n", affiliations=("La\x03b",)),),
        journal="J\x04",
        doi="10.1/a\x05b",
        license=License(spdx="CC\x06", holder="H\x07"),
        keywords=("k\x08",),
    )
    result = render_epub(doc_of(meta=meta), tmp_path / "book.epub")
    book = Book(result.path)
    for name in ("content.opf", "nav.xhtml", "front-matter.xhtml"):
        book.xml(name)
    assert "epub.invalid_xml_chars" in {p.code for p in result.problems}
    assert book.xml("content.opf").find(f"{OPF}metadata/{DC}title").text == "Title"


def test_a_title_of_only_control_characters_still_gives_a_valid_book(tmp_path):
    book = render(tmp_path, doc_of(meta=Meta(title="\x01")))
    assert book.xml("content.opf").find(f"{OPF}metadata/{DC}title").text == "Untitled"


def test_blank_metadata_values_are_left_out_of_the_opf(tmp_path):
    meta = Meta(title="T", authors=(Author(name=" \x01"),), journal="\x02", keywords=("",))
    metadata = render(tmp_path, doc_of(meta=meta)).xml("content.opf").find(f"{OPF}metadata")
    tags = {element.tag.removeprefix(DC) for element in metadata}
    assert not tags & {"creator", "publisher", "subject"}


def test_a_heading_of_only_control_characters_keeps_its_toc_entry(tmp_path):
    book = render(tmp_path, doc_of(Heading(id="h", level=1, number="\x03", runs=(Text("\x01"),))))
    assert find(book.xml("nav.xhtml"), "a")[0].text == "Section 1"


# Any text at all has to produce a well-formed book.
any_text = st.text(st.characters(codec=None, exclude_categories=()), max_size=30)


@settings(max_examples=60, deadline=None)
@given(any_text, any_text, any_text)
def test_arbitrary_text_always_gives_well_formed_parts(title, body, href):
    blocks = (
        Heading(id="h", level=1, number=body, runs=(Text(title),)),
        Paragraph(id="p", runs=(Text(body), Link(href, (MathInline(body),)))),
        ListItem(id="l", runs=(Cite(body, (Text(body),)),)),
        Equation(id="e", alt=body, latex=body),
        Table(id="t", number=body, caption=(Text(body),), header=((Text(body),),), rows=()),
        Reference(id="r", runs=(Text(body),), key=body, doi=body),
    )
    meta = Meta(title=title, authors=(Author(name=body),), keywords=(body,))
    with tempfile.TemporaryDirectory() as directory:
        book = Book(render_epub(doc_of(*blocks, meta=meta), Path(directory) / "b.epub").path)
    for name, data in book.files.items():
        if name.endswith((".xhtml", ".opf", ".xml")):
            ElementTree.fromstring(data)


# Refusing bad input


def test_invalid_documents_are_refused(tmp_path):
    doc = doc_of(Figure(id="f", number="1", asset="missing", caption=()))
    with pytest.raises(EpubRenderError, match="asset.unresolved"):
        render_epub(doc, tmp_path / "book.epub")
    assert not (tmp_path / "book.epub").exists()


def test_output_directory_is_created(tmp_path):
    result = render_epub(doc_of(), tmp_path / "a" / "b" / "book.epub")
    assert result.path.is_file()


# epubcheck


def test_epubcheck_accepts_the_hand_built_book(tmp_path):
    epubcheck = shutil.which("epubcheck")
    if epubcheck is None:
        pytest.skip(
            "epubcheck is not on PATH (brew install epubcheck), so EPUB validity is unknown"
        )
    path = render_epub(full_doc(), tmp_path / "book.epub", cover=png(16, 24)).path
    result = subprocess.run([epubcheck, str(path)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_identifier_survives_a_lone_surrogate_in_an_author_name() -> None:
    meta = Meta(title="T", authors=(Author(name="A\ud800"),))

    assert book_identifier(meta, "T") == book_identifier(
        replace(meta, authors=(Author(name="A"),)), "T"
    )


# Rendered math


def chapter_root(path: Path) -> ElementTree.Element:
    return Book(path).xml("front-matter.xhtml")


MATH_ASSET = Asset(
    id="m",
    mime="image/png",
    bytes=png(mode="LA", color=(0, 255)),
    box=MathBox(width=2.5, height=1.2, depth=0.35),
)


def test_inline_math_image_sits_on_the_baseline_and_keeps_its_latex(tmp_path):
    paragraph = Paragraph(id="p", runs=(Text("a "), MathInline("", r"\frac{a}{b}", "m")))
    result = render_epub(doc_of(paragraph, assets=(MATH_ASSET,)), tmp_path / "b.epub")
    image = find(chapter_root(result.path), "img")[0]
    assert image.get("alt") == r"\frac{a}{b}"
    assert image.get("class") == "math-inline"
    assert image.get("style") == "width:2.500em;vertical-align:-0.350em"
    assert result.problems == ()


def test_inline_math_image_without_metrics_is_still_shown(tmp_path):
    paragraph = Paragraph(id="p", runs=(MathInline("x", None, "a"),))
    doc = doc_of(paragraph, assets=(asset("a", png()),))
    result = render_epub(doc, tmp_path / "b.epub")
    image = find(chapter_root(result.path), "img")[0]
    assert image.get("alt") == "x"
    assert image.get("style") is None


def test_inline_math_without_an_image_is_text_and_reported(tmp_path):
    paragraph = Paragraph(id="p", runs=(MathInline("", r"\bad"),))
    result = render_epub(doc_of(paragraph), tmp_path / "b.epub")
    assert r"\bad" in text_of(chapter_root(result.path))
    assert [(p.code, p.block_id) for p in result.problems] == [
        ("epub.inline_math_text_fallback", "p")
    ]


def test_inline_math_that_never_had_latex_is_just_text(tmp_path):
    paragraph = Paragraph(id="p", runs=(MathInline("x + y"),))
    assert render_epub(doc_of(paragraph), tmp_path / "b.epub").problems == ()


def test_display_math_image_is_sized_in_em_with_the_latex_as_alt(tmp_path):
    equation = Equation(id="e", alt="a over b", number="2", latex=r"\frac{a}{b}", asset="m")
    result = render_epub(doc_of(equation, assets=(MATH_ASSET,)), tmp_path / "b.epub")
    image = find(chapter_root(result.path), "img")[0]
    assert image.get("alt") == r"\frac{a}{b}"
    assert image.get("class") == "math-display"
    assert "width:2.500em" in image.get("style")


def test_a_cropped_equation_stays_as_it_was(tmp_path):
    doc = doc_of(Equation(id="e", alt="E = mc2", asset="a"), assets=(asset("a", png()),))
    image = find(chapter_root(render_epub(doc, tmp_path / "b.epub").path), "img")[0]
    assert image.get("alt") == "E = mc2"
    assert image.get("style") is None
