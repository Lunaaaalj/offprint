"""Explicit publisher profiles through the public conversion paths (#34)."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from offprint import pipeline
from offprint.adapters.pdf import convert_pdf, read_evidence
from offprint.cli import app
from offprint.ir import from_json
from offprint.profiles import Profile, load_profile_file
from offprint.sources import Doi, Resolution, cache

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"
PROFILE = Path(__file__).parents[1] / "src" / "offprint" / "profiles" / "frontiers.yaml"
runner = CliRunner()


@pytest.fixture
def profile_file(tmp_path: Path) -> Path:
    path = tmp_path / "publisher.yaml"
    shutil.copy(PROFILE, path)
    return path


def test_explicit_profile_emits_the_same_fixture_ir(profile_file: Path, tmp_path: Path) -> None:
    outdir = tmp_path / "ir"
    result = runner.invoke(
        app, ["convert", str(PDF), "--profile", str(profile_file), "--emit-ir", "-o", str(outdir)]
    )
    assert result.exit_code == 0, result.output
    restored = from_json((outdir / "paper.ir.json").read_text(), outdir / "paper.assets")
    assert restored == convert_pdf(PDF)


@pytest.mark.parametrize("cached", [False, True], ids=["local", "cached"])
def test_epub_and_qa_use_the_same_loaded_override(
    profile_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cached: bool
) -> None:
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(tmp_path / "no-config.toml"))
    # An explicit profile must work even when its automatic match rules don't fit.
    profile_file.write_text(profile_file.read_text().replace("MinionPro, MuseoSans", "NoSuchFont"))
    expected_profile = load_profile_file(profile_file)
    expected_doc = convert_pdf(PDF, expected_profile)
    expected_evidence = read_evidence(PDF, expected_profile)
    seen: list[Profile] = []

    def convert(path: Path, profile: Profile | None = None):
        assert profile == expected_profile
        seen.append(profile)
        doc = convert_pdf(path, profile)
        assert doc == expected_doc
        # Neither QA nor the CLI should re-read the file or silently auto-select.
        profile_file.unlink()
        return doc

    def evidence(path: Path, profile: Profile | None = None):
        assert profile is seen[0]
        result = read_evidence(path, profile)
        assert result == expected_evidence
        seen.append(profile)
        return result

    monkeypatch.setattr(pipeline, "convert_pdf", convert)
    monkeypatch.setattr(pipeline, "read_evidence", evidence)
    source = str(PDF)
    if cached:
        target = Doi("10.3389/frai.2026.1748985")
        cache.store(
            tmp_path / "cache",
            target,
            Resolution(input=str(target), attempts=(), tier="pdf"),
            "source.pdf",
            PDF.read_bytes(),
        )
        source = str(target)
    result = runner.invoke(
        app,
        [
            "convert",
            source,
            "--profile",
            str(profile_file),
            "--no-cover",
            "-o",
            str(tmp_path / "book"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(seen) == 2
    assert Path(result.stdout.strip()).is_file()


@pytest.mark.parametrize("emit_ir", [False, True], ids=["epub", "ir"])
@pytest.mark.parametrize("kind", ["missing", "yaml", "schema", "encoding", "directory"])
def test_bad_profile_is_a_readable_error_without_output(
    kind: str, emit_ir: bool, tmp_path: Path
) -> None:
    path = tmp_path / "bad.yaml"
    if kind == "yaml":
        path.write_text("page: [")
    elif kind == "schema":
        path.write_text(PROFILE.read_text().replace("header_y: 50", "header_y: wrong"))
    elif kind == "encoding":
        path.write_bytes(b"\xff")
    elif kind == "directory":
        path.mkdir()
    outdir = tmp_path / "out"
    args = ["convert", str(PDF), "--profile", str(path), "--no-cover", "-o", str(outdir)]
    if emit_ir:
        args.append("--emit-ir")
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert str(path) in result.stderr
    if kind == "schema":
        assert "page.header_y" in result.stderr
    assert not result.stdout
    assert not outdir.exists()
    if not emit_ir:
        with pytest.raises(pipeline.ConvertError, match="bad.yaml"):
            pipeline.convert_to_epub(str(PDF), outdir, profile=path)


def test_profile_is_not_silently_ignored_for_xml(profile_file: Path, tmp_path: Path) -> None:
    xml = tmp_path / "paper.xml"
    xml.write_text("<article/>")
    with pytest.raises(pipeline.ConvertError, match="only to PDF"):
        pipeline.convert_to_epub(str(xml), tmp_path / "out", profile=profile_file)
