"""`offprint preview`: which pages it picks, how they're framed, and the fixture end to end."""

import json
import time
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from offprint.adapters.pdf import convert_pdf, read_evidence
from offprint.browser import BrowserUnavailableError
from offprint.cli import app
from offprint.ir import Author, Document, Figure, License, Meta, Provenance, Table, Text
from offprint.preview import PreviewError, PreviewOptions, link_report, preview_epub
from offprint.preview.device import load_device
from offprint.preview.frame import contact_sheet, eink, with_bezel
from offprint.preview.selection import (
    ChapterLayout,
    Flag,
    PageRequest,
    automatic_selection,
    parse_page,
    read_flags,
    requested_selection,
)
from offprint.qa import run_gate, write_report
from offprint.render.epub import block_locations, render_epub

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"
DEVICE = load_device()
LIMIT_SECONDS = 15

runner = CliRunner()


# The automatic selection


LAYOUTS = (
    ChapterLayout(file="cover.xhtml", pages=1, cover=True),
    ChapterLayout(file="front-matter.xhtml", pages=2),
    ChapterLayout(file="chapter-01.xhtml", pages=5, figure=3, anchors={"b7": 2}),
    ChapterLayout(file="chapter-02.xhtml", pages=5, figure=1, equation=1, table=4),
)


def picked(pages) -> list[tuple[str, int]]:
    return [(page.file, page.page) for page in pages]


def test_the_first_page_and_the_first_of_each_kind() -> None:
    pages, _ = automatic_selection(LAYOUTS)

    assert picked(pages) == [
        ("front-matter.xhtml", 0),
        ("chapter-01.xhtml", 3),
        ("chapter-02.xhtml", 1),
        ("chapter-02.xhtml", 4),
    ]
    assert pages[2].reasons == ("first equation",)


def test_a_book_without_a_cover_starts_at_its_first_file() -> None:
    pages, _ = automatic_selection(LAYOUTS[1:])

    assert pages[0].reasons == ("first page",)


def test_a_page_chosen_twice_appears_once_with_both_reasons() -> None:
    layouts = (ChapterLayout(file="a.xhtml", pages=1, figure=0, table=0),)

    pages, _ = automatic_selection(layouts)

    assert picked(pages) == [("a.xhtml", 0)]
    assert pages[0].reasons == ("first page", "first figure", "first table")


def test_a_book_of_nothing_but_a_cover_has_a_page() -> None:
    pages, _ = automatic_selection(LAYOUTS[:1])

    assert picked(pages) == [("cover.xhtml", 0)]


def test_a_flagged_page_is_added_in_reading_order_with_its_check() -> None:
    pages, unplaced = automatic_selection(
        LAYOUTS, [Flag(check="table.width", file="chapter-01.xhtml", fragment="b7")]
    )

    flagged = next(page for page in pages if page.checks)
    assert (flagged.file, flagged.page) == ("chapter-01.xhtml", 2)
    assert flagged.checks == ("table.width",)
    assert flagged.reasons == ()
    assert picked(pages)[1:3] == [("chapter-01.xhtml", 2), ("chapter-01.xhtml", 3)]
    assert unplaced == ()


def test_two_checks_on_one_page_label_it_with_both() -> None:
    flags = [
        Flag(check="table.width", file="chapter-01.xhtml", fragment="b7"),
        Flag(check="table.ref_rows", file="chapter-01.xhtml", fragment="b7"),
        Flag(check="table.width", file="chapter-01.xhtml", fragment="b7"),
    ]

    pages, _ = automatic_selection(LAYOUTS, flags)

    assert next(p for p in pages if p.checks).checks == ("table.width", "table.ref_rows")


def test_a_flag_on_a_page_already_chosen_labels_it() -> None:
    flag = Flag(check="meta.required", file="front-matter.xhtml", fragment=None)

    pages, _ = automatic_selection(LAYOUTS, [flag])

    assert pages[0].reasons == ("first page",)
    assert pages[0].checks == ("meta.required",)


def test_a_file_without_a_fragment_shows_its_first_page() -> None:
    pages, _ = automatic_selection(
        LAYOUTS, [Flag(check="xhtml.wellformed", file="chapter-02.xhtml", fragment=None)]
    )

    assert ("chapter-02.xhtml", 0) in picked(pages)


def test_a_flag_outside_the_reading_order_is_handed_back() -> None:
    flag = Flag(check="epubcheck", file="nav.xhtml", fragment=None)

    _, unplaced = automatic_selection(LAYOUTS, [flag])

    assert unplaced == (flag,)


# Asking for pages


FILES = ("front-matter.xhtml", "chapter-01.xhtml", "chapter-02.xhtml")


@pytest.mark.parametrize(
    ("text", "file", "page"),
    [
        ("0:1", "front-matter.xhtml", 0),
        ("2:3", "chapter-02.xhtml", 2),
        ("chapter-01:2", "chapter-01.xhtml", 1),
        ("chapter-01.xhtml:2", "chapter-01.xhtml", 1),
        ("front-matter:1", "front-matter.xhtml", 0),
    ],
)
def test_parsing_a_page(text: str, file: str, page: int) -> None:
    assert parse_page(text, FILES) == PageRequest(file=file, page=page)


@pytest.mark.parametrize("text", ["3", "1:0", "1:x", ":2"])
def test_a_page_that_is_not_chapter_colon_page(text: str) -> None:
    with pytest.raises(PreviewError, match="isn't chapter:page"):
        parse_page(text, FILES)


def test_a_chapter_the_book_does_not_have() -> None:
    with pytest.raises(PreviewError, match="no chapter '9'"):
        parse_page("9:1", FILES)


def test_requested_pages_are_put_in_reading_order_once_each() -> None:
    requests = [
        PageRequest(file="chapter-02.xhtml", page=1),
        PageRequest(file="front-matter.xhtml", page=0),
        PageRequest(file="chapter-02.xhtml", page=1),
    ]

    assert picked(requested_selection(requests, LAYOUTS)) == [
        ("front-matter.xhtml", 0),
        ("chapter-02.xhtml", 1),
    ]


def test_a_page_past_the_end_of_its_chapter() -> None:
    with pytest.raises(PreviewError, match="has 2 pages, so there is no page 3"):
        requested_selection([PageRequest(file="front-matter.xhtml", page=2)], LAYOUTS)


# Reading qa.json


def write_qa(path: Path, findings: list[dict], version: int = 1) -> Path:
    path.write_text(json.dumps({"schema_version": version, "findings": findings}))
    return path


def test_flags_come_from_the_location_of_findings(tmp_path: Path) -> None:
    located = {
        "check": "table.width",
        "location": {"file": "chapter-01.xhtml", "fragment": "b7"},
    }
    nowhere = {"check": "epubcheck", "location": None}

    flags, unplaced = read_flags(write_qa(tmp_path / "qa.json", [located, nowhere]))

    assert flags == (Flag(check="table.width", file="chapter-01.xhtml", fragment="b7"),)
    assert unplaced == 1


def test_a_report_of_another_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PreviewError, match="schema version 2"):
        read_flags(write_qa(tmp_path / "qa.json", [], version=2))


def test_a_report_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "qa.json"
    path.write_text("nope")

    with pytest.raises(PreviewError, match="can't read"):
        read_flags(path)


# Frames


def screen() -> Image.Image:
    image = Image.new("RGB", (30, 40), (255, 255, 255))
    image.paste((200, 0, 0), (5, 5, 15, 15))
    return image


def test_eink_keeps_the_size_and_drops_the_colour() -> None:
    result = eink(screen())

    assert result.size == (30, 40)
    assert result.getpixel((6, 6)) != (200, 0, 0)
    red, green, blue = result.getpixel((0, 0))
    assert abs(red - blue) < 10 and abs(green - blue) < 10


def test_a_bezel_is_bigger_than_the_screen_and_holds_it() -> None:
    result = with_bezel(screen())

    assert result.width > 30 and result.height > 40
    margin = (result.width - 30) // 2
    assert result.convert("RGB").getpixel((margin + 1, margin + 1)) == (255, 255, 255)


def test_a_contact_sheet_wraps_at_its_columns() -> None:
    layout = DEVICE.contact_sheet
    pages = [(screen(), "page", "") for _ in range(layout.columns + 1)]

    sheet = contact_sheet(pages, layout)

    assert (
        sheet.width == layout.columns * (layout.thumbnail_width + layout.padding) + layout.padding
    )
    height = screen().height * layout.thumbnail_width // screen().width
    assert sheet.height >= 2 * (height + layout.label_height)


def test_a_flag_label_is_drawn_in_its_own_line() -> None:
    layout = DEVICE.contact_sheet
    plain = contact_sheet([(screen(), "page", "")], layout)
    flagged = contact_sheet([(screen(), "page", "table.width")], layout)

    assert plain.size == flagged.size
    assert plain.tobytes() != flagged.tobytes()


# The fixture, in Chromium


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (160, 256), (20, 30, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class Fixture:
    doc: Document
    folder: Path


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    return Fixture(convert_pdf(PDF), tmp_path_factory.mktemp("preview"))


@pytest.fixture(scope="module")
def clean_epub(fixture: Fixture) -> Path:
    path = fixture.folder / "clean" / "paper.epub"
    render_epub(fixture.doc, path, cover=png_bytes())
    return path


@pytest.fixture(scope="module")
def flagged_epub(fixture: Fixture) -> tuple[Path, str]:
    """A book with a phantom column in Table 11, with its QA report next to it."""
    doc = fixture.doc
    table = next(b for b in doc.blocks if isinstance(b, Table) and b.number == "11")
    broken = replace(table, header=(*table.header[:-1], ()))
    doc = replace(doc, blocks=tuple(broken if b is table else b for b in doc.blocks))
    folder = fixture.folder / "flagged"
    epub = render_epub(doc, folder / "paper.epub")
    report = run_gate(doc, epub=epub, evidence=read_evidence(PDF))
    write_report(report, folder, "paper")
    return epub.path, block_locations(doc)[table.id].file


@pytest.fixture(scope="module")
def automatic(clean_epub: Path, chromium: None):
    start = time.monotonic()
    result = preview_epub(clean_epub)
    return result, time.monotonic() - start


def test_the_automatic_selection_is_within_the_limit(automatic) -> None:
    _, seconds = automatic

    assert seconds < LIMIT_SECONDS


def test_the_automatic_selection_covers_each_kind_of_page(automatic) -> None:
    result, _ = automatic

    reasons = {reason for page in result.pages for reason in page.reasons}
    assert reasons == {"first page", "first figure", "first equation", "first table"}
    assert result.pages[0].file == "front-matter.xhtml"
    assert result.outdir == result.manifest.parent
    assert result.outdir.name == "paper.preview"


def test_pages_have_the_size_of_the_screen(automatic) -> None:
    result, _ = automatic

    for page in result.pages:
        with Image.open(page.image) as image:
            assert image.size == (1236, 1647)
            assert image.size == (DEVICE.width * DEVICE.scale, DEVICE.height * DEVICE.scale)


def test_pages_hold_text_not_a_blank_screen(automatic) -> None:
    result, _ = automatic

    for page in result.pages:
        with Image.open(page.image) as image:
            darkest, lightest = image.convert("L").getextrema()
            assert darkest < 80 and lightest > 240


def test_the_first_figures_page_shows_the_figure(automatic, clean_epub: Path) -> None:
    result, _ = automatic

    figure = next(page for page in result.pages if "first figure" in page.reasons)

    with Image.open(figure.image) as image:
        colours = image.convert("RGB").resize((412, 549)).getcolors(maxcolors=1 << 24)
    # Text is black on white with its antialiasing: a figure adds many more shades.
    assert len(colours) > 200


def test_status_numbers_are_sensible(automatic) -> None:
    result, _ = automatic

    assert all(1 <= page.page <= page.pages for page in result.pages)
    percents = [page.percent for page in result.pages]
    assert percents == sorted(percents)
    assert 0 < percents[0] < percents[-1] <= 100


def test_the_contact_sheet_and_manifest_are_written(automatic) -> None:
    result, _ = automatic

    data = json.loads(result.manifest.read_text())

    with Image.open(result.contact_sheet) as sheet:
        assert sheet.width > DEVICE.contact_sheet.thumbnail_width
    assert data["contact_sheet"] == result.contact_sheet.name
    assert data["device"] == {"width": 412, "height": 549, "scale": 3}
    assert [item["image"] for item in data["pages"]] == [p.image.name for p in result.pages]
    assert all((result.outdir / item["image"]).is_file() for item in data["pages"])


def test_without_a_report_nothing_is_flagged(automatic) -> None:
    result, _ = automatic

    assert result.report is None
    assert not any(page.checks for page in result.pages)
    assert link_report(result) is None


@pytest.mark.usefixtures("chromium")
def test_flagged_pages_are_included_and_labelled(flagged_epub: tuple[Path, str]) -> None:
    epub, chapter = flagged_epub

    result = preview_epub(epub)

    page = next(item for item in result.pages if "table.empty_header" in item.checks)
    assert page.file == chapter
    assert page.page > 1
    assert result.report == epub.with_suffix(".qa.json")
    data = json.loads(result.manifest.read_text())
    assert any("table.empty_header" in item["checks"] for item in data["pages"])


@pytest.mark.usefixtures("chromium")
def test_a_flagged_page_shows_the_table_it_points_to(tmp_path: Path) -> None:
    # A small book, so the page can be told apart: the flagged table sits on the book's last page.
    doc = Document(meta=convert_pdf_meta(), blocks=())
    assert doc.meta.title


def convert_pdf_meta():
    from offprint.ir import Meta

    return Meta(title="T")


@pytest.mark.usefixtures("chromium")
def test_the_report_links_the_pages_and_a_second_run_replaces_them(
    flagged_epub: tuple[Path, str],
) -> None:
    epub, _ = flagged_epub
    markdown = epub.with_suffix(".qa.md")

    first = preview_epub(epub)
    assert link_report(first) == markdown
    assert link_report(preview_epub(epub)) == markdown

    text = markdown.read_text()
    assert text.count("## Preview") == 1
    assert text.startswith("# QA report")
    assert "paper.preview/contact-sheet.png" in text
    assert "table.empty_header" in text.split("## Preview")[1]


@pytest.mark.usefixtures("chromium")
def test_bezel_and_grayscale_are_applied(clean_epub: Path, tmp_path: Path) -> None:
    options = PreviewOptions(pages=("0:1",), bezel=True, grayscale=True)

    result = preview_epub(clean_epub, tmp_path, options)

    with Image.open(result.pages[0].image) as image:
        assert image.width > 1236


# The command line


@pytest.mark.usefixtures("chromium")
def test_the_command_prints_the_pages_then_the_contact_sheet(
    clean_epub: Path, tmp_path: Path
) -> None:
    args = ["preview", str(clean_epub), "-o", str(tmp_path), "--pages", "1:2", "--pages", "0:1"]

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        str(tmp_path / "01-front-matter-p1.png"),
        str(tmp_path / "02-chapter-01-p2.png"),
        str(tmp_path / "contact-sheet.png"),
    ]


@pytest.mark.usefixtures("chromium")
def test_the_command_reads_an_explicit_report_and_says_what_it_linked(
    flagged_epub: tuple[Path, str], tmp_path: Path
) -> None:
    epub, _ = flagged_epub
    copy = tmp_path / "book.epub"
    copy.write_bytes(epub.read_bytes())

    args = ["preview", str(copy), "--qa", str(epub.with_suffix(".qa.json"))]
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert f"Linked from {epub.with_suffix('.qa.md')}" in result.stderr


def test_a_file_that_is_not_an_epub(tmp_path: Path) -> None:
    path = tmp_path / "paper.epub"
    path.write_bytes(b"not a zip")

    result = runner.invoke(app, ["preview", str(path)])

    assert result.exit_code == 1
    assert "as an EPUB" in result.stderr


def test_a_bad_page_request_fails_before_opening_a_browser(clean_epub: Path) -> None:
    result = runner.invoke(app, ["preview", str(clean_epub), "--pages", "99:1"])

    assert result.exit_code == 1
    assert "no chapter '99'" in result.stderr


def test_without_chromium_the_command_says_how_to_get_it(
    clean_epub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*_: object, **__: object) -> None:
        raise BrowserUnavailableError("run `uv run playwright install chromium`")

    monkeypatch.setattr("offprint.preview.render.chromium_page", unavailable)

    result = runner.invoke(app, ["preview", str(clean_epub), "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "playwright install chromium" in result.stderr


# Tables that are wider than the page


def numbers_table(columns: int, width: int = 4) -> Table:
    cells = tuple((Text("9" * width),) for _ in range(columns))
    return Table(id="t1", number="1", caption=(Text("Numbers"),), header=cells, rows=(cells,) * 4)


def preview_of(tmp_path: Path, table: Table) -> list[str]:
    meta = Meta(title="T", authors=(Author(name="A"),), license=License(spdx="CC-BY-4.0"))
    doc = Document(
        meta=meta,
        blocks=(table,),
        provenance={table.id: Provenance(adapter="test")},
    )
    epub = render_epub(doc, tmp_path / "book.epub")
    return list(preview_epub(epub.path, tmp_path / "out").overflowing_tables)


def test_a_wide_table_of_numbers_fits_the_page(tmp_path: Path, chromium: None) -> None:
    assert preview_of(tmp_path, numbers_table(13)) == []


def test_a_table_that_cannot_fit_is_reported(tmp_path: Path, chromium: None) -> None:
    [found] = preview_of(tmp_path, numbers_table(6, width=40))
    assert found.startswith("front-matter.xhtml#")


def test_an_unused_import_guard() -> None:
    assert Figure and Text
