"""PDF adapter: rebuild a paper's structure from a PDF using a publisher profile (#3).

`extract` reads the PDF and is the only module that knows PyMuPDF. Everything after it works on the
plain data in `offprint.extraction`, steered by the profile.
"""

from functools import partial
from pathlib import Path

from offprint.adapters.pdf.assemble import LayoutError, assemble
from offprint.adapters.pdf.extract import (
    citation_metadata,
    crop,
    document_facts,
    open_pdf,
    read_pages,
)
from offprint.ir import Document, to_json, validate
from offprint.profiles import NoProfileMatch, Profile, select_profile


def convert_pdf(path: Path, profile: Profile | None = None) -> Document:
    """Convert a PDF to the IR. Raises `NoProfileMatch` if no profile fits its template."""
    with open_pdf(path) as pdf:
        profile = profile or select_profile(document_facts(pdf))
        return assemble(
            read_pages(pdf, profile.fonts),
            profile,
            crop=partial(crop, pdf),
            pdf_metadata=citation_metadata(pdf),
        )


def emit_ir(path: Path, outdir: Path) -> Path:
    """Convert a PDF and write `<stem>.ir.json`, with assets in `<stem>.assets/`, to `outdir`.

    Returns the path of the JSON. A document that fails `validate` is an error, not a file.
    """
    doc = convert_pdf(path)
    problems = validate(doc)
    if problems:
        listed = "; ".join(f"{problem.code}: {problem.message}" for problem in problems)
        raise LayoutError(f"the IR is invalid: {listed}")
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / f"{path.stem}.ir.json"
    target.write_text(to_json(doc, outdir / f"{path.stem}.assets"), encoding="utf-8")
    return target


__all__ = ["LayoutError", "NoProfileMatch", "convert_pdf", "emit_ir"]
