"""A local PDF of an arXiv paper takes the licence `offprint resolve` cached for it (#60).

`convert` makes no network calls: it only reads the cache. The NeurIPS fixture is arXiv
2611.09197, CC BY 4.0 on arXiv, and its PDF prints no licence.
"""

import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from offprint import pipeline
from offprint.adapters.pdf import PdfResult
from offprint.ir import Author, Document, Heading, License, Meta, Provenance, Text
from offprint.pipeline import ConvertError, cached_arxiv_meta, convert_to_epub
from offprint.sources import ArxivId, CacheError, Resolution, arxiv, cache

FIXTURES = Path(__file__).parent / "fixtures"
NEURIPS_PDF = FIXTURES / "neurips-2026-2611.09197" / "paper.pdf"
OTHER_PDF = FIXTURES / "frontiers-frai-2026-1748985" / "paper.pdf"
RECORDING = Path(__file__).parent / "recordings" / "arxiv-neurips-metadata"
NEURIPS = ArxivId("2611.09197")
CC_BY = License(spdx="CC-BY-4.0")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No sockets, and no real cache or config: the configured cache is an empty temp dir."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("convert tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(tmp_path / "configured-cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(tmp_path / "no-such-config.toml"))


def recorded_meta() -> Meta:
    """arXiv's real record of the fixture, with the licence from its OAI-PMH response."""
    recording = json.loads((RECORDING / "exchanges.json").read_text(encoding="utf-8"))
    bodies = {item["url"]: RECORDING / item["body"] for item in recording["exchanges"]}
    [record] = arxiv.parse_feed(bodies[arxiv.query_url(NEURIPS)].read_bytes())
    license_ = arxiv.parse_oai_license(bodies[arxiv.oai_url(NEURIPS)].read_bytes())
    return replace(record.meta, license=license_, source_tier="latex")


def store(cache_dir: Path, meta: Meta | None, target: ArxivId = NEURIPS) -> None:
    """A cache entry as `resolve` leaves it. Its source file doesn't matter to a local convert."""
    resolution = Resolution(input=str(target), attempts=(), meta=meta, tier="pdf")
    cache.store(cache_dir, target, resolution, "source.pdf", b"%PDF-1.7 placeholder")


def tiny(arxiv_id: str | None) -> Document:
    meta = Meta(title="T", authors=(Author(name="A"),), arxiv_id=arxiv_id)
    heading = Heading(id="h", level=1, runs=(Text("One"),))
    return Document(
        meta=meta, blocks=(heading,), provenance={"h": Provenance(adapter="test", page=1)}
    )


def convert_tiny(monkeypatch: pytest.MonkeyPatch, doc: Document, outdir: Path, cache_dir: Path):
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(doc, ()))
    monkeypatch.setattr(pipeline, "read_evidence", lambda *_, **kwargs: None)
    return convert_to_epub(str(OTHER_PDF), outdir, cover=False, cache_dir=cache_dir)


def meta_required(conversion) -> tuple[str, list[str]]:
    [result] = [check for check in conversion.report.checks if check.id == "meta.required"]
    messages = [f.message for f in conversion.report.findings if f.check == "meta.required"]
    return result.status, messages


# cached_arxiv_meta


def test_the_recording_holds_the_fixtures_license() -> None:
    meta = recorded_meta()

    assert (meta.arxiv_id, meta.license) == ("2611.09197", CC_BY)


def test_a_resolved_arxiv_id_gives_its_cached_meta(tmp_path: Path) -> None:
    store(tmp_path, recorded_meta())

    found = cached_arxiv_meta("2611.09197", tmp_path)

    assert found is not None and found.license == CC_BY


@pytest.mark.parametrize("arxiv_id", [None, "", "2611.09197", "not an id"])
def test_nothing_is_found_without_a_resolved_id(arxiv_id: str | None, tmp_path: Path) -> None:
    assert cached_arxiv_meta(arxiv_id, tmp_path) is None


def test_another_papers_entry_is_not_used(tmp_path: Path) -> None:
    store(tmp_path, recorded_meta(), target=ArxivId("2610.22829"))

    assert cached_arxiv_meta("2611.09197", tmp_path) is None


def test_a_damaged_entry_is_an_error_not_a_miss(tmp_path: Path) -> None:
    store(tmp_path, recorded_meta())
    (cache.entry_dir(tmp_path, NEURIPS) / "source.pdf").write_bytes(b"changed")

    with pytest.raises(CacheError, match="offprint resolve --refresh"):
        cached_arxiv_meta("2611.09197", tmp_path)


# convert_to_epub


def test_a_local_file_takes_the_cached_license(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store(tmp_path / "cache", recorded_meta())

    conversion = convert_tiny(monkeypatch, tiny("2611.09197"), tmp_path, tmp_path / "cache")

    assert meta_required(conversion) == ("pass", [])


def test_without_a_cache_entry_the_message_names_the_resolve_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    conversion = convert_tiny(monkeypatch, tiny("2611.09197"), tmp_path, tmp_path / "cache")

    status, [message] = meta_required(conversion)
    assert status == "fail"
    assert "run `offprint resolve arXiv:2611.09197 --refresh`, then convert again" in message


def test_an_entry_without_a_license_still_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # arXiv's non-exclusive licence maps to no licence at all.
    store(tmp_path / "cache", replace(recorded_meta(), license=None))

    conversion = convert_tiny(monkeypatch, tiny("2611.09197"), tmp_path, tmp_path / "cache")

    assert meta_required(conversion)[0] == "fail"


def test_the_configured_cache_is_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store(tmp_path / "configured-cache", recorded_meta())
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(tiny("2611.09197"), ()))
    monkeypatch.setattr(pipeline, "read_evidence", lambda *_, **kwargs: None)

    conversion = convert_to_epub(str(OTHER_PDF), tmp_path, cover=False)

    assert meta_required(conversion) == ("pass", [])


def test_a_damaged_entry_stops_the_book(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store(tmp_path / "cache", recorded_meta())
    (cache.entry_dir(tmp_path / "cache", NEURIPS) / "source.pdf").write_bytes(b"changed")

    with pytest.raises(ConvertError, match="is damaged"):
        convert_tiny(monkeypatch, tiny("2611.09197"), tmp_path / "out", tmp_path / "cache")
    assert not (tmp_path / "out").exists()


def test_a_paper_without_an_arxiv_id_never_reads_the_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_: object) -> None:
        raise AssertionError("the cache was read")

    monkeypatch.setattr(cache, "load", fail)

    conversion = convert_tiny(monkeypatch, tiny(None), tmp_path, tmp_path / "cache")

    assert meta_required(conversion)[1] == ["the paper has no license"]


# The NeurIPS fixture end to end


def test_the_neurips_pdf_passes_meta_required_with_its_resolved_entry(tmp_path: Path) -> None:
    store(tmp_path / "cache", recorded_meta())

    conversion = convert_to_epub(
        str(NEURIPS_PDF), tmp_path, cover=False, cache_dir=tmp_path / "cache"
    )

    assert meta_required(conversion) == ("pass", [])
    failed = {result.id for result in conversion.report.checks if result.status == "fail"}
    assert "meta.required" not in failed
