"""The conversion pipeline: from an INPUT to a finished EPUB, without touching the network.

input → `cached_source` → adapter → `validate` → `generate_cover` → `render_epub`

Every failure the user can act on becomes a `ConvertError`, with a message for the terminal.
"""

from dataclasses import replace
from pathlib import Path

from offprint.adapters.pdf import LayoutError, NoProfileMatch, UnreadablePdfError, convert_pdf
from offprint.browser import BrowserUnavailableError
from offprint.cover import CoverLayoutError, generate_cover
from offprint.ir import Document, Meta, SourceTier, validate
from offprint.render.epub import EpubRenderError, EpubResult, render_epub
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
    "jats": "the best source for {input} is JATS XML, but that adapter doesn't exist yet (#10)",
    "ml": "the best source for {input} needs the ML adapter, which doesn't exist yet (#16)",
}


class ConvertError(Exception):
    """The paper can't be converted, and no EPUB was written."""


def convert_to_epub(source: str, outdir: Path, *, cover: bool = True) -> EpubResult:
    """Convert `source`, a local file or a cached identifier, to `outdir/<name>.epub`."""
    try:
        target = detect_input(source)
        resolution = cached_source(source)
    except SourceError as error:
        raise ConvertError(str(error)) from error

    doc = _read_document(resolution)
    doc = replace(doc, meta=combine_meta(doc.meta, resolution.meta))
    if problems := validate(doc):
        listed = "; ".join(f"{problem.code}: {problem.message}" for problem in problems)
        raise ConvertError(f"the IR is invalid: {listed}")

    cover_png = _render_cover(doc) if cover else None
    try:
        return render_epub(doc, outdir / f"{output_stem(target)}.epub", cover=cover_png)
    except (EpubRenderError, OSError) as error:
        raise ConvertError(str(error)) from error


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


def _read_document(resolution: Resolution) -> Document:
    if resolution.tier != "pdf" or resolution.path is None:
        template = _MISSING_ADAPTERS.get(resolution.tier or "ml", "no source for {input}")
        raise ConvertError(template.format(input=resolution.input))
    try:
        return convert_pdf(resolution.path)
    except (LayoutError, NoProfileMatch, UnreadablePdfError) as error:
        raise ConvertError(str(error)) from error


def _render_cover(doc: Document) -> bytes:
    try:
        return generate_cover(doc)
    except (BrowserUnavailableError, CoverLayoutError) as error:
        raise ConvertError(f"can't make the cover: {error}. Use --no-cover to skip it.") from error
