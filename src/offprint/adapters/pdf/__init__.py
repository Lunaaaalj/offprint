"""PDF adapter: rebuild a paper's structure from a PDF using a publisher profile (#3).

`extract` reads the PDF and is the only module that knows PyMuPDF. Everything after it works on the
plain data in `offprint.extraction`, steered by the profile.
"""

from dataclasses import dataclass
from functools import partial
from pathlib import Path

from offprint.adapters.pdf.assemble import LayoutError, assemble
from offprint.adapters.pdf.evidence import collect_evidence
from offprint.adapters.pdf.extract import (
    UnreadablePdfError,
    citation_metadata,
    crop,
    document_facts,
    open_pdf,
    read_pages,
    read_text,
)
from offprint.extraction import SourceEvidence
from offprint.ir import Document, Problem, to_json, validate
from offprint.profiles import NoProfileMatch, Profile, select_profile


@dataclass(frozen=True, slots=True)
class PdfResult:
    document: Document
    problems: tuple[Problem, ...]
    """What the adapter couldn't place, for the QA gate."""


def read_pdf(path: Path, profile: Profile | None = None) -> PdfResult:
    """Convert a PDF to the IR, with the problems found on the way.

    Raises `NoProfileMatch` if no profile fits its template.
    """
    problems: list[Problem] = []
    with open_pdf(path) as pdf:
        profile = profile or select_profile(document_facts(pdf))
        document = assemble(
            read_pages(pdf, profile.fonts),
            profile,
            crop=partial(crop, pdf),
            pdf_metadata=citation_metadata(pdf),
            problems=problems,
        )
    return PdfResult(document, tuple(problems))


def convert_pdf(path: Path, profile: Profile | None = None) -> Document:
    """Convert a PDF to the IR. Raises `NoProfileMatch` if no profile fits its template."""
    return read_pdf(path, profile).document


def emit_ir(path: Path, outdir: Path, profile: Profile | None = None) -> Path:
    """Convert a PDF and write `<stem>.ir.json`, with assets in `<stem>.assets/`, to `outdir`.

    Returns the path of the JSON. A document that fails `validate` is an error, not a file.
    """
    doc = convert_pdf(path, profile=profile)
    problems = validate(doc)
    if problems:
        listed = "; ".join(f"{problem.code}: {problem.message}" for problem in problems)
        raise LayoutError(f"the IR is invalid: {listed}")
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / f"{path.stem}.ir.json"
    target.write_text(to_json(doc, outdir / f"{path.stem}.assets"), encoding="utf-8")
    return target


def read_evidence(path: Path, profile: Profile | None = None) -> SourceEvidence:
    """Read what the QA gate compares the book with. It takes no part in the conversion."""
    with open_pdf(path) as pdf:
        profile = profile or select_profile(document_facts(pdf))
        return collect_evidence(read_text(pdf, profile.fonts), profile)


__all__ = [
    "LayoutError",
    "NoProfileMatch",
    "PdfResult",
    "UnreadablePdfError",
    "convert_pdf",
    "emit_ir",
    "read_evidence",
    "read_pdf",
]
