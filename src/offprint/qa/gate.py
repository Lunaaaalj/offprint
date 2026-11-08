"""The gate: run every check, locate what they found, and reach a verdict.

`run_gate` keeps to what's here, the document, the source's evidence and the finished EPUB, and uses
no network. Checks that need something that's absent are skipped, and the report says so.
"""

from collections.abc import Mapping
from dataclasses import replace
from itertools import chain

from offprint.extraction import SourceEvidence
from offprint.ir import Document, Equation, Figure, Heading, Table, validate
from offprint.qa import checks
from offprint.qa.book import Book, BookError, read_book, reading_text, xhtml_wellformed
from offprint.qa.catalog import CHECKS
from offprint.qa.config import QaConfig, load_config
from offprint.qa.coverage import word_coverage
from offprint.qa.epubcheck import run_epubcheck
from offprint.qa.model import CheckResult, Counts, Finding, Outcome, QaReport, Status
from offprint.render.epub import BookLocation, EpubResult, block_locations

_IR_CODES = (
    "block.duplicate_id",
    "provenance.missing",
    "provenance.unknown_block",
    "asset.unresolved",
    "asset.id_mismatch",
    "figure.duplicate_number",
    "table.duplicate_number",
    "table.width",
    "equation.empty",
    "heading.level",
    "heading.jump",
)
# Problems the adapter, the equation stage and the renderer reported, in `EpubResult.problems`.
_CONVERSION_CODES = tuple(
    check.id for check in CHECKS if check.id.startswith(("epub.", "jats.", "math."))
)
_COVER_CODES = tuple(check.id for check in CHECKS if check.id.startswith("cover."))


def _book_outcomes(
    doc: Document, epub: EpubResult | None, evidence: SourceEvidence | None, config: QaConfig
) -> dict[str, Outcome]:
    """Run the checks of the finished file."""
    book: Book | None = None
    error: str | None = "no EPUB was written" if epub is None else None
    if epub is not None:
        try:
            book = read_book(epub.path)
        except BookError as failure:
            error = str(failure)

    if epub is None or book is None:
        skipped = Outcome(skipped=error)
        unreadable = checks.finding("xhtml.wellformed", error or "")
        return {
            "xhtml.wellformed": skipped if epub is None else Outcome(findings=(unreadable,)),
            "coverage.words": skipped,
            "epubcheck": skipped,
        }

    if evidence is None:
        coverage = Outcome(skipped="nothing to compare with: no evidence from this source")
    else:
        coverage = word_coverage(doc, evidence, reading_text(book), config)
    return {
        "xhtml.wellformed": xhtml_wellformed(book),
        "coverage.words": coverage,
        "epubcheck": run_epubcheck(epub.path, timeout=config.epubcheck_timeout, root=book.root),
    }


def _outcomes(
    doc: Document,
    epub: EpubResult | None,
    evidence: SourceEvidence | None,
    cover: bool,
    config: QaConfig,
) -> dict[str, Outcome]:
    cover_outcome = Outcome() if cover else Outcome(skipped="this book has no cover")
    return {
        **_book_outcomes(doc, epub, evidence, config),
        "counts.figures": checks.counts_figures(doc, evidence),
        "counts.tables": checks.counts_tables(doc, evidence),
        "counts.equations": checks.counts_equations(doc, evidence),
        "table.empty_header": checks.table_empty_header(doc),
        "table.ref_rows": checks.table_ref_rows(doc, config),
        "figure.foreign_caption": checks.figure_foreign_caption(doc, evidence, config),
        "reference.numbering": checks.reference_numbering(doc, config),
        "meta.required": checks.meta_required(doc),
        **checks.problem_outcomes(validate(doc), _IR_CODES),
        **checks.problem_outcomes(epub.problems if epub else (), _CONVERSION_CODES),
        # A cover that fails these stops the conversion, so one that exists has passed them.
        **dict.fromkeys(_COVER_CODES, cover_outcome),
    }


def _located(
    finding: Finding,
    doc: Document,
    locations: Mapping[str, BookLocation],
    first_on_page: Mapping[int, str],
) -> Finding:
    """Fill in where a finding is, in the source and in the book, from what it already says.

    A finding with only a source page points to the first block read from that page.
    """
    if finding.location is not None:
        return finding
    block_id = finding.block_id
    if block_id is None and finding.page is not None:
        block_id = first_on_page.get(finding.page)
    place = doc.provenance.get(finding.block_id) if finding.block_id else None
    return replace(
        finding,
        page=finding.page or (place.page if place else None),
        bbox=finding.bbox or (place.bbox if place else None),
        location=locations.get(block_id) if block_id else None,
    )


def _first_blocks(doc: Document) -> dict[int, str]:
    """Map each source page to the first block read from it."""
    first: dict[int, str] = {}
    for block in doc.blocks:
        place = doc.provenance.get(block.id)
        if place is not None and place.page is not None:
            first.setdefault(place.page, block.id)
    return first


def _status(outcome: Outcome) -> Status:
    if outcome.skipped is not None:
        return "skip"
    severities = {finding.severity for finding in outcome.findings}
    if "error" in severities:
        return "fail"
    return "warn" if severities else "pass"


def _score(results: tuple[CheckResult, ...], config: QaConfig) -> float:
    """Return the share of the checks that ran and passed, with warnings at their weight."""
    weights: dict[Status, float] = {"pass": 1.0, "warn": config.warn_weight, "fail": 0.0}
    ran = [weights[result.status] for result in results if result.status != "skip"]
    return round(sum(ran) / len(ran), 3) if ran else 0.0


def _counts(doc: Document, evidence: SourceEvidence | None) -> Counts:
    def blocks(kind: type) -> list:
        return [block for block in doc.blocks if isinstance(block, kind)]

    return Counts(
        pages=evidence.pages if evidence else None,
        figures=len(blocks(Figure)),
        tables=len(blocks(Table)),
        equations=sum(1 for equation in blocks(Equation) if equation.number is not None),
        sections=sum(1 for heading in blocks(Heading) if heading.level == 1),
    )


def run_gate(
    doc: Document,
    *,
    epub: EpubResult | None = None,
    evidence: SourceEvidence | None = None,
    cover: bool = False,
    config: QaConfig | None = None,
) -> QaReport:
    """Check a conversion. `doc` is what reached the renderer and `epub` what came out of it."""
    config = config or load_config()
    outcomes = _outcomes(doc, epub, evidence, cover, config)
    results = tuple(
        CheckResult(
            id=check.id,
            severity=check.severity,
            status=_status(outcomes[check.id]),
            hint=check.hint,
            findings=len(outcomes[check.id].findings),
            reason=outcomes[check.id].skipped,
            value=outcomes[check.id].value,
            threshold=outcomes[check.id].threshold,
        )
        for check in CHECKS
    )
    locations = block_locations(doc)
    first_on_page = _first_blocks(doc)
    findings = tuple(
        _located(finding, doc, locations, first_on_page)
        for finding in chain.from_iterable(outcomes[check.id].findings for check in CHECKS)
    )
    failed = any(result.status == "fail" for result in results)
    return QaReport(
        title=doc.meta.title,
        epub=epub.path.name if epub else None,
        verdict="review" if failed else "pass",
        score=_score(results, config),
        counts=_counts(doc, evidence),
        checks=results,
        findings=findings,
    )
