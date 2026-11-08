"""The conversion pipeline: from an INPUT to a finished EPUB, without touching the network.

input → `cached_source` → adapter → `typeset_math` → `validate` → `generate_cover` → `render_epub`
→ `run_gate`

Every failure the user can act on becomes a `ConvertError`, with a message for the terminal, and
writes nothing. A book that reaches the gate is written with its report, whatever the verdict.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from offprint.adapters.jats import JatsError, convert_jats
from offprint.adapters.jats import read_evidence as read_jats_evidence
from offprint.adapters.pdf import (
    LayoutError,
    NoProfileMatch,
    UnreadablePdfError,
    read_evidence,
    read_pdf,
)
from offprint.browser import BrowserUnavailableError
from offprint.cover import CoverLayoutError, generate_cover
from offprint.equations import typeset_math
from offprint.extraction import SourceEvidence
from offprint.ir import Document, Meta, Problem, SourceTier, validate
from offprint.profiles import Profile, ProfileError, load_profile_file
from offprint.qa import QaReport, run_gate, write_report
from offprint.render.epub import EpubRenderError, render_epub
from offprint.sources import (
    LocalFile,
    Resolution,
    SourceError,
    SourceInput,
    cached_source,
    detect_input,
    identifier_slug,
)

_MISSING_ADAPTERS: dict[SourceTier, str] = {
    "latex": "the best source for {input} is LaTeX, but that adapter doesn't exist yet (#11)",
    "ml": "the best source for {input} needs the ML adapter, which doesn't exist yet (#16)",
}


class ConvertError(Exception):
    """The paper can't be converted, and no EPUB was written."""


@dataclass(frozen=True, slots=True)
class Conversion:
    path: Path
    problems: tuple[Problem, ...]
    report: QaReport
    report_path: Path
    """The readable report. The JSON one is next to it."""


def convert_to_epub(
    source: str, outdir: Path, *, cover: bool = True, profile: Path | None = None
) -> Conversion:
    """Convert `source`, a local file or a cached identifier, to `outdir/<name>.epub`."""
    try:
        target = detect_input(source)
        resolution = cached_source(source)
    except SourceError as error:
        raise ConvertError(str(error)) from error

    if profile is not None and resolution.tier != "pdf":
        raise ConvertError("--profile applies only to PDF sources")
    try:
        selected_profile = load_profile_file(profile) if profile is not None else None
    except ProfileError as error:
        raise ConvertError(str(error)) from error

    doc, adapter_problems = _read_document(resolution, selected_profile)
    doc = replace(doc, meta=combine_meta(doc.meta, resolution.meta))
    typeset = typeset_math(doc)
    doc = typeset.doc
    if problems := validate(doc):
        listed = "; ".join(f"{problem.code}: {problem.message}" for problem in problems)
        raise ConvertError(f"the IR is invalid: {listed}")

    cover_png = _render_cover(doc) if cover else None
    stem = output_stem(target)
    try:
        epub = render_epub(doc, outdir / f"{stem}.epub", cover=cover_png)
        epub = replace(epub, problems=(*adapter_problems, *typeset.problems, *epub.problems))
        report = run_gate(
            doc,
            epub=epub,
            evidence=_read_evidence(resolution, selected_profile),
            cover=cover_png is not None,
        )
        _, report_path = write_report(report, outdir, stem)
    except (EpubRenderError, OSError) as error:
        raise ConvertError(str(error)) from error
    return Conversion(epub.path, epub.problems, report, report_path)


def combine_meta(extracted: Meta, resolved: Meta | None) -> Meta:
    """Combine what the adapter read with what the resolver looked up. Pure.

    The resolver wins on the fields a registry curates: title, journal, year, volume, article id,
    DOI and arXiv id. The adapter wins on what it reads from the paper itself, which is richer:
    authors (affiliations, corresponding author), abstract (inline markup), license (the holder),
    keywords and source tier. On every field, the other side fills a gap.
    """
    if resolved is None:
        return extracted
    # Crossref uses the DOI as the title of a work that has none.
    placeholder = resolved.title.casefold() == (resolved.doi or "").casefold()
    title = (extracted.title or resolved.title) if placeholder else resolved.title
    return replace(
        extracted,
        title=title or extracted.title,
        journal=resolved.journal or extracted.journal,
        year=resolved.year or extracted.year,
        volume=resolved.volume or extracted.volume,
        article_id=resolved.article_id or extracted.article_id,
        doi=resolved.doi or extracted.doi,
        arxiv_id=resolved.arxiv_id or extracted.arxiv_id,
        authors=extracted.authors or resolved.authors,
        abstract=extracted.abstract or resolved.abstract,
        license=extracted.license or resolved.license,
        keywords=extracted.keywords or resolved.keywords,
    )


def output_stem(target: SourceInput) -> str:
    """The EPUB's file name, without the extension. Pure."""
    if isinstance(target, LocalFile):
        return target.path.stem
    return identifier_slug(target)


def _read_document(
    resolution: Resolution, profile: Profile | None = None
) -> tuple[Document, tuple[Problem, ...]]:
    """Run the source's adapter. Returns the document and what the adapter couldn't map."""
    if resolution.tier not in ("pdf", "jats") or resolution.path is None:
        template = _MISSING_ADAPTERS.get(resolution.tier or "ml", "no source for {input}")
        raise ConvertError(template.format(input=resolution.input))
    try:
        if resolution.tier == "jats":
            result = convert_jats(resolution.path)
            return result.document, result.problems
        result = read_pdf(resolution.path, profile=profile)
        return result.document, result.problems
    except (JatsError, LayoutError, NoProfileMatch, UnreadablePdfError) as error:
        raise ConvertError(str(error)) from error


def _read_evidence(resolution: Resolution, profile: Profile | None = None) -> SourceEvidence | None:
    """Read what the gate compares with. A source without any has its checks skipped, not failed."""
    if resolution.path is None:
        return None
    try:
        if resolution.tier == "jats":
            return read_jats_evidence(resolution.path)
        return read_evidence(resolution.path, profile=profile) if resolution.tier == "pdf" else None
    except (JatsError, NoProfileMatch, UnreadablePdfError):
        return None


def _render_cover(doc: Document) -> bytes:
    try:
        return generate_cover(doc)
    except (BrowserUnavailableError, CoverLayoutError) as error:
        raise ConvertError(f"can't make the cover: {error}. Use --no-cover to skip it.") from error
