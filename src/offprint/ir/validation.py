"""Structural rules every Document must satisfy, reported as problems with stable codes."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from offprint.ir.model import BBox, Document, Equation, Figure, Heading, MathInline, Run, Table
from offprint.ir.walk import iter_runs, map_runs


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    message: str
    block_id: str | None = None
    page: int | None = None
    """Where it is in the source, for a problem that has no block."""
    bbox: BBox | None = None


def validate(doc: Document) -> list[Problem]:
    """Return every rule `doc` breaks; an empty list means it's valid."""
    return [
        *_check_block_ids(doc),
        *_check_provenance(doc),
        *_check_assets(doc),
        *_check_numbers(doc, Figure, "figure"),
        *_check_numbers(doc, Table, "table"),
        *_check_tables(doc),
        *_check_equations(doc),
        *_check_headings(doc),
    ]


def _check_block_ids(doc: Document) -> list[Problem]:
    counts = Counter(block.id for block in doc.blocks)
    return [
        Problem("block.duplicate_id", f"{count} blocks share the id {block_id!r}", block_id)
        for block_id, count in counts.items()
        if count > 1
    ]


def _check_provenance(doc: Document) -> list[Problem]:
    block_ids = {block.id for block in doc.blocks}
    missing = [
        Problem("provenance.missing", f"block {block_id!r} has no provenance", block_id)
        for block_id in dict.fromkeys(block.id for block in doc.blocks)
        if block_id not in doc.provenance
    ]
    unknown = [
        Problem("provenance.unknown_block", f"provenance for unknown block {block_id!r}")
        for block_id in doc.provenance
        if block_id not in block_ids
    ]
    return missing + unknown


def _check_assets(doc: Document) -> list[Problem]:
    problems = [
        Problem("asset.id_mismatch", f"asset stored under {key!r} has the id {asset.id!r}")
        for key, asset in doc.assets.items()
        if key != asset.id
    ]
    for block in doc.blocks:
        if isinstance(block, Figure | Equation) and block.asset is not None:
            if block.asset not in doc.assets:
                message = f"block {block.id!r} points to the missing asset {block.asset!r}"
                problems.append(Problem("asset.unresolved", message, block.id))
        problems += _check_inline_assets(doc, iter_runs(block), block.id)
    leaves: list[Run] = []
    map_runs(doc.meta.abstract, lambda run: leaves.append(run) or (run,))
    problems += _check_inline_assets(doc, leaves, None)
    return problems


def _check_inline_assets(doc: Document, runs: Iterable[Run], block_id: str | None) -> list[Problem]:
    return [
        Problem(
            "asset.unresolved", f"inline math points to the missing asset {run.asset!r}", block_id
        )
        for run in runs
        if isinstance(run, MathInline) and run.asset is not None and run.asset not in doc.assets
    ]


def _check_numbers(doc: Document, kind: type[Figure | Table], name: str) -> list[Problem]:
    problems = []
    seen = set()
    for block in doc.blocks:
        if isinstance(block, kind):
            if block.number in seen:
                message = f"{name} {block.number!r} appears more than once"
                problems.append(Problem(f"{name}.duplicate_number", message, block.id))
            seen.add(block.number)
    return problems


def _check_tables(doc: Document) -> list[Problem]:
    problems = []
    for block in doc.blocks:
        if isinstance(block, Table):
            width = len(block.header)
            for index, row in enumerate(block.rows):
                if len(row) != width:
                    message = (
                        f"table {block.number!r} row {index} has {len(row)} cells, not {width}"
                    )
                    problems.append(Problem("table.width", message, block.id))
    return problems


def _check_equations(doc: Document) -> list[Problem]:
    return [
        Problem("equation.empty", f"equation {block.id!r} has no latex and no asset", block.id)
        for block in doc.blocks
        if isinstance(block, Equation) and block.latex is None and block.asset is None
    ]


def _check_headings(doc: Document) -> list[Problem]:
    problems = []
    previous = 0  # The document root, so the first heading must be level 1.
    for block in doc.blocks:
        if isinstance(block, Heading):
            if block.level < 1:
                message = f"heading {block.id!r} has level {block.level}"
                problems.append(Problem("heading.level", message, block.id))
            elif block.level > previous + 1:
                message = f"heading {block.id!r} jumps from level {previous} to {block.level}"
                problems.append(Problem("heading.jump", message, block.id))
            previous = block.level
    return problems
