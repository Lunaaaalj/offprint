"""`offprint convert`: the pipeline's rules, each failure path and the fixture end to end."""

import json
import re
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from offprint import pipeline
from offprint.browser import BrowserUnavailableError
from offprint.cli import app
from offprint.cover import CoverLayoutError
from offprint.ir import Author, Document, Heading, License, Meta, Problem, Text
from offprint.pipeline import combine_meta, convert_to_epub, output_stem
from offprint.render.epub import EpubResult
from offprint.sources import ArxivId, Doi, Resolution, cache, crossref, detect_input

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"
RECORDING = Path(__file__).parent / "recordings" / "fixture-doi"
DOI = Doi("10.3389/frai.2026.1748985")
ARXIV = ArxivId("2401.01234")
XHTML = "{http://www.w3.org/1999/xhtml}"
TINY = Document(meta=Meta(title="T", doi="10.1234/x"))

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(tmp_path / "no-such-config.toml"))


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any connection or name lookup, and on building the resolver's HTTP client."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("convert tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr("offprint.sources.resolver.Http", refuse)


def cached_entry(
    target: Doi | ArxivId,
    tmp_path: Path,
    *,
    filename: str = "source.pdf",
    body: bytes | None = None,
    meta: Meta | None = None,
) -> None:
    tier = {"source.pdf": "pdf", "source.xml": "jats", "source.tar.gz": "latex"}[filename]
    resolution = Resolution(input=str(target), attempts=(), meta=meta, tier=tier)
    data = PDF.read_bytes() if body is None else body
    cache.store(tmp_path / "cache", target, resolution, filename, data)


def run(*args: str | Path):
    return runner.invoke(app, ["convert", *map(str, args)])


def crossref_meta() -> Meta:
    """The real Crossref record of the fixture paper."""
    recording = json.loads((RECORDING / "exchanges.json").read_text())
    found = next(item for item in recording["exchanges"] if "api.crossref.org" in item["url"])
    return crossref.parse_work(json.loads((RECORDING / found["body"]).read_bytes())).meta


# Combining metadata


EXTRACTED = Meta(
    title="Extracted title",
    authors=(Author(name="A. Author", affiliation="Somewhere", corresponding=True),),
    journal="Front. Artif. Intell.",
    year=2025,
    volume="8",
    article_id="1",
    doi="10.1/extracted",
    license=License(spdx="CC-BY-4.0", holder="The authors"),
    abstract=(Text("Extracted abstract"),),
    keywords=("kept",),
    source_tier="pdf",
)
RESOLVED = Meta(
    title="Registry title",
    authors=(Author(name="Ann Author"),),
    journal="Frontiers in Artificial Intelligence",
    year=2026,
    volume="9",
    article_id="2",
    doi="10.1/resolved",
    arxiv_id="2401.01234",
    license=License(spdx="CC-BY-NC-4.0"),
    abstract=(Text("Registry abstract"),),
    source_tier="jats",
)


def test_without_resolver_metadata_the_adapter_is_unchanged() -> None:
    assert combine_meta(EXTRACTED, None) is EXTRACTED


@pytest.mark.parametrize("field", ["title", "journal", "year", "volume", "article_id", "doi"])
def test_the_resolver_wins_on_registry_fields(field: str) -> None:
    assert getattr(combine_meta(EXTRACTED, RESOLVED), field) == getattr(RESOLVED, field)


@pytest.mark.parametrize("field", ["authors", "license", "abstract", "keywords", "source_tier"])
def test_the_adapter_wins_on_what_the_paper_prints(field: str) -> None:
    assert getattr(combine_meta(EXTRACTED, RESOLVED), field) == getattr(EXTRACTED, field)


def test_each_side_fills_the_other_sides_gaps() -> None:
    empty = Meta(title="")

    assert combine_meta(empty, RESOLVED).authors == RESOLVED.authors
    assert combine_meta(empty, RESOLVED).license == RESOLVED.license
    assert combine_meta(empty, RESOLVED).abstract == RESOLVED.abstract
    assert combine_meta(EXTRACTED, empty) == EXTRACTED
    assert combine_meta(EXTRACTED, RESOLVED).arxiv_id == "2401.01234"


def test_crossrefs_placeholder_title_never_replaces_a_real_one() -> None:
    resolved = Meta(title="10.1/UPPER", doi="10.1/upper")

    assert combine_meta(EXTRACTED, resolved).title == "Extracted title"
    assert combine_meta(Meta(title=""), resolved).title == "10.1/UPPER"


# Output names


@pytest.mark.parametrize(
    ("text", "stem"),
    [
        ("some/dir/paper.pdf", "paper"),
        ("10.3389/frai.2026.1748985", "10.3389_frai.2026.1748985"),
        ("2401.01234v2", "2401.01234v2"),
        ("hep-th/9901001", "hep-th_9901001"),
    ],
)
def test_output_stem(text: str, stem: str) -> None:
    assert output_stem(detect_input(text)) == stem


# Failures: each exits non-zero with a specific message and writes nothing


def test_a_missing_file(tmp_path: Path) -> None:
    result = run(tmp_path / "absent.pdf", "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert "no such file" in result.stderr


def test_an_input_that_is_nothing_we_know() -> None:
    result = run("paper.docx")

    assert result.exit_code == 1
    assert "can't tell what" in result.stderr


def test_a_file_that_is_not_a_pdf(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"not a pdf")

    result = run(path, "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert "as a PDF" in result.stderr


def test_a_pdf_no_profile_fits(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    with pymupdf.open() as blank:
        blank.new_page()
        blank.save(path)

    result = run(path, "-o", tmp_path / "out", "--no-cover")

    assert result.exit_code == 1
    assert "profile" in result.stderr


@pytest.mark.parametrize("text", [str(DOI), str(ARXIV)])
def test_an_uncached_identifier_names_the_resolve_command(text: str, no_network: None) -> None:
    result = run(text)

    assert result.exit_code == 1
    assert f"run `offprint resolve {text}`" in result.stderr


@pytest.mark.parametrize(("filename", "issue"), [("source.xml", "#10"), ("source.tar.gz", "#11")])
def test_a_source_without_an_adapter_names_its_issue(
    filename: str, issue: str, tmp_path: Path
) -> None:
    cached_entry(DOI, tmp_path, filename=filename, body=b"source")

    result = run(DOI, "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert issue in result.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(("path", "issue"), [("paper.xml", "#10"), ("paper.tar.gz", "#11")])
def test_a_local_source_without_an_adapter_names_its_issue(
    path: str, issue: str, tmp_path: Path
) -> None:
    (tmp_path / path).write_bytes(b"source")

    result = run(tmp_path / path, "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert issue in result.stderr


def test_a_damaged_cache_entry_says_how_to_recover(tmp_path: Path) -> None:
    cached_entry(DOI, tmp_path, body=b"%PDF")
    (cache.entry_dir(tmp_path / "cache", DOI) / "source.pdf").write_bytes(b"changed")

    result = run(DOI)

    assert result.exit_code == 1
    assert "--refresh" in result.stderr


def test_an_invalid_ir_is_refused_before_the_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heading = Heading(id="same", level=1, runs=(Text("One"),))
    invalid = Document(meta=Meta(title="T"), blocks=(heading, replace(heading)))
    monkeypatch.setattr(pipeline, "convert_pdf", lambda _: invalid)

    def no_cover_expected(_: Document) -> bytes:
        raise AssertionError("an invalid document reached the cover")

    monkeypatch.setattr(pipeline, "generate_cover", no_cover_expected)

    result = run(PDF, "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert "the IR is invalid" in result.stderr
    assert "block.duplicate_id" in result.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "failure",
    [
        BrowserUnavailableError("run `uv run playwright install chromium`"),
        CoverLayoutError([Problem("cover.overflow", "the title leaves the page")]),
    ],
)
def test_a_failed_cover_stops_the_book_and_mentions_no_cover(
    failure: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_: Document) -> bytes:
        raise failure

    monkeypatch.setattr(pipeline, "convert_pdf", lambda _: TINY)
    monkeypatch.setattr(pipeline, "generate_cover", fail)

    result = run(PDF, "-o", tmp_path / "out")

    assert result.exit_code == 1
    assert str(failure) in result.stderr
    assert "--no-cover" in result.stderr
    assert not (tmp_path / "out").exists()


# What a successful run prints and writes


def test_no_cover_skips_the_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_cover_expected(_: Document) -> bytes:
        raise AssertionError("--no-cover still generated a cover")

    monkeypatch.setattr(pipeline, "convert_pdf", lambda _: TINY)
    monkeypatch.setattr(pipeline, "generate_cover", no_cover_expected)

    result = run(PDF, "-o", tmp_path, "--no-cover")

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(tmp_path / "paper.epub")
    assert not any("cover" in name for name in zipfile.ZipFile(tmp_path / "paper.epub").namelist())


def test_rendering_problems_are_printed_after_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "convert_pdf", lambda _: TINY)
    monkeypatch.setattr(pipeline, "render_epub", _render_with_a_problem)

    result = run(PDF, "-o", tmp_path, "--no-cover")

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(tmp_path / "paper.epub")
    assert "epub.link_dropped: a link went away" in result.stderr


def _render_with_a_problem(_: Document, path: Path, cover: bytes | None = None) -> EpubResult:
    return EpubResult(path, (Problem("epub.link_dropped", "a link went away"),))


def test_the_resolvers_metadata_reaches_the_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached_entry(DOI, tmp_path, body=b"%PDF", meta=RESOLVED)
    monkeypatch.setattr(pipeline, "convert_pdf", lambda _: TINY)

    result = convert_to_epub(str(DOI), tmp_path / "out", cover=False)

    assert result.path == tmp_path / "out" / "10.3389_frai.2026.1748985.epub"
    with zipfile.ZipFile(result.path) as book:
        assert "Registry title" in book.read("OEBPS/content.opf").decode()


# The fixture, end to end


@pytest.fixture(scope="module")
def book(chromium: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    outdir = tmp_path_factory.mktemp("book")
    result = runner.invoke(app, ["convert", str(PDF), "-o", str(outdir)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str(outdir / "paper.epub")
    return outdir / "paper.epub"


def test_the_fixture_book_has_every_part(book: Path) -> None:
    with zipfile.ZipFile(book) as archive:
        chapters = [
            archive.read(name).decode()
            for name in archive.namelist()
            if re.search(r"(chapter-\d+|front-matter)\.xhtml$", name)
        ]
        nav = archive.read("OEBPS/nav.xhtml").decode()
        names = archive.namelist()
    text = "".join(chapters)

    assert len(re.findall(r"<figure\b", text)) == 24
    assert len(re.findall(r"<table\b", text)) == 20
    assert len(re.findall(r'class="equation"', text)) == 18
    toc = ElementTree.fromstring(nav).find(f".//{XHTML}nav[@id='toc']/{XHTML}ol")
    assert toc is not None
    assert len(toc.findall(f"{XHTML}li")) == 15
    assert "OEBPS/images/cover.png" in names


def test_the_fixture_book_passes_epubcheck(book: Path) -> None:
    epubcheck = shutil.which("epubcheck")
    if epubcheck is None:
        pytest.skip(
            "epubcheck is not on PATH (brew install epubcheck), so EPUB validity is unknown"
        )
    result = subprocess.run([epubcheck, str(book)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


# No network: the real path, with a cover, for both kinds of input


@pytest.mark.usefixtures("chromium", "no_network")
def test_a_local_file_converts_offline(tmp_path: Path) -> None:
    result = run(PDF, "-o", tmp_path)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "paper.epub").is_file()


@pytest.mark.usefixtures("chromium", "no_network")
def test_a_cached_identifier_converts_offline_with_real_crossref_metadata(tmp_path: Path) -> None:
    cached_entry(DOI, tmp_path, meta=crossref_meta())

    result = run(DOI, "-o", tmp_path)

    assert result.exit_code == 0, result.output
    path = tmp_path / "10.3389_frai.2026.1748985.epub"
    with zipfile.ZipFile(path) as book:
        package = book.read("OEBPS/content.opf").decode()
    assert "Artificial intelligence techniques" in package
