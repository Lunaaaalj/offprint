"""The checks of the document itself. Each is a pure function from the IR, and maybe the source."""

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from offprint.cleanup import plain_text
from offprint.cleanup.geometry import area, intersection_area
from offprint.extraction import SourceCaption, SourceEvidence
from offprint.ir import BBox, Document, Equation, Figure, Problem, Table
from offprint.qa.catalog import BY_ID
from offprint.qa.config import QaConfig
from offprint.qa.model import Finding, Outcome
from offprint.render.epub import FRONT_MATTER_LOCATION

_NO_SOURCE = "nothing to compare with: no evidence was read from this source"
_NO_PAGES = "this source has no pages, so its figures aren't crops that could take in a caption"


def finding(check: str, message: str, **where: object) -> Finding:
    """Build a finding of `check` at its usual severity."""
    return Finding(check=check, message=message, severity=BY_ID[check].severity, **where)


def _numbered(doc: Document, kind: type[Figure | Table | Equation]) -> list[tuple[str, str]]:
    """Return each numbered block of a kind, as (number, block id)."""
    return [
        (block.number.strip("()"), block.id)
        for block in doc.blocks
        if isinstance(block, kind) and block.number is not None
    ]


def _sequence_findings(check: str, label: str, numbers: Sequence[tuple[str, str]]) -> list[Finding]:
    """Find numbers that aren't 1..n once each. "S1" and "A.2" aren't part of that series."""
    found = []
    counts = Counter(number for number, _ in numbers)
    for number, block_id in numbers:
        if not number.strip():
            found.append(finding(check, f"a {label} has no number", block_id=block_id))
    for number, count in counts.items():
        if number.strip() and count > 1:
            block_id = next(block for value, block in numbers if value == number)
            message = f"{label} {number} appears {count} times"
            found.append(finding(check, message, block_id=block_id))
    plain = sorted((int(number), block) for number, block in numbers if number.isdecimal())
    if plain:
        by_number = dict(plain)
        for expected in range(1, plain[-1][0]):
            if expected not in by_number:
                before = max((n for n in by_number if n < expected), default=plain[0][0])
                message = f"{label} {expected} is missing from the numbering"
                found.append(finding(check, message, block_id=by_number[before]))
    return found


def _count_outcome(
    check: str,
    label: str,
    numbers: Sequence[tuple[str, str]],
    source: Sequence[tuple[str, int | None, BBox | None]] | None,
) -> Outcome:
    """Compare a kind's blocks with what the source shows, and check their numbering."""
    found = _sequence_findings(check, label, numbers)
    if source is not None:
        extracted = {number for number, _ in numbers}
        places = {number: (page, bbox) for number, page, bbox in reversed(source)}
        for number, (page, bbox) in places.items():
            if number not in extracted:
                message = f"the source shows {label} {number}, but the document doesn't have it"
                found.append(finding(check, message, page=page, bbox=bbox))
        for number, block_id in numbers:
            if number not in places:
                message = f"{label} {number} was extracted, but the source doesn't show it"
                found.append(finding(check, message, block_id=block_id))
    return Outcome(findings=tuple(found), value=float(len(numbers)))


def _caption_places(
    evidence: SourceEvidence | None, kind: str
) -> list[tuple[str, int | None, BBox | None]] | None:
    if evidence is None:
        return None
    return [
        (caption.number, caption.page, caption.bbox)
        for caption in evidence.captions
        if caption.kind == kind and not caption.continued
    ]


def counts_figures(doc: Document, evidence: SourceEvidence | None) -> Outcome:
    places = _caption_places(evidence, "figure")
    return _count_outcome("counts.figures", "figure", _numbered(doc, Figure), places)


def counts_tables(doc: Document, evidence: SourceEvidence | None) -> Outcome:
    places = _caption_places(evidence, "table")
    return _count_outcome("counts.tables", "table", _numbered(doc, Table), places)


def counts_equations(doc: Document, evidence: SourceEvidence | None) -> Outcome:
    places = None
    if evidence is not None:
        places = [(item.number, item.page, item.bbox) for item in evidence.equations]
    return _count_outcome("counts.equations", "equation", _numbered(doc, Equation), places)


def _tables(doc: Document) -> Iterable[Table]:
    return (block for block in doc.blocks if isinstance(block, Table))


def table_empty_header(doc: Document) -> Outcome:
    return Outcome(
        findings=tuple(
            finding(
                "table.empty_header",
                f"table {table.number} has an empty header in column {index}",
                block_id=table.id,
            )
            for table in _tables(doc)
            for index, cell in enumerate(table.header, start=1)
            if not plain_text(cell)
        )
    )


def table_ref_rows(doc: Document, config: QaConfig) -> Outcome:
    found = []
    for table in _tables(doc):
        if not table.header or plain_text(table.header[0]) not in config.reference_headers:
            continue
        for index, row in enumerate(table.rows, start=1):
            first = plain_text(row[0]) if row else ""
            if re.search(config.year_pattern, first) is None:
                message = f"table {table.number} row {index} doesn't end in a year: {first!r}"
                found.append(finding("table.ref_rows", message, block_id=table.id))
    return Outcome(findings=tuple(found))


def _is_inside(caption: SourceCaption, box: BBox, config: QaConfig) -> bool:
    if caption.bbox is None:
        return False
    shared = intersection_area(caption.bbox, box)
    return shared > 0 and shared >= config.foreign_caption_overlap * area(caption.bbox)


def figure_foreign_caption(
    doc: Document, evidence: SourceEvidence | None, config: QaConfig
) -> Outcome:
    """Find figures that took in another caption.

    Provenance gives the box of the crop and its own caption together, so this compares captions
    by their number: a figure's box can only hold its own.
    """
    if evidence is None:
        return Outcome(skipped=_NO_SOURCE)
    if evidence.pages is None:
        return Outcome(skipped=_NO_PAGES)
    found = []
    for block in doc.blocks:
        place = doc.provenance.get(block.id)
        if not isinstance(block, Figure) or place is None or place.bbox is None:
            continue
        for caption in evidence.captions:
            own = caption.kind == "figure" and caption.number == block.number
            if not own and caption.page == place.page and _is_inside(caption, place.bbox, config):
                message = f"figure {block.number} contains the caption of {_label(caption)}"
                found.append(finding("figure.foreign_caption", message, block_id=block.id))
    return Outcome(findings=tuple(found))


def _label(caption: SourceCaption) -> str:
    return f"{caption.kind} {caption.number}"


def meta_required(doc: Document) -> Outcome:
    meta = doc.meta
    missing = [
        name
        for name, present in (
            ("title", meta.title.strip()),
            ("author", meta.authors),
            ("license", meta.license),
        )
        if not present
    ]
    return Outcome(
        findings=tuple(
            finding("meta.required", f"the paper has no {name}", location=FRONT_MATTER_LOCATION)
            for name in missing
        )
    )


def problem_outcomes(problems: Iterable[Problem], check_ids: Iterable[str]) -> dict[str, Outcome]:
    """Report problems from elsewhere (`validate`, the renderer) under the codes they came with."""
    grouped: dict[str, list[Finding]] = {check_id: [] for check_id in check_ids}
    for problem in problems:
        grouped.setdefault(problem.code, []).append(
            finding(problem.code, problem.message, block_id=problem.block_id)
        )
    return {code: Outcome(findings=tuple(found)) for code, found in grouped.items()}
