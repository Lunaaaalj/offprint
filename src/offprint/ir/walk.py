"""Reach every run in a block, however deeply nested. Pure."""

from collections.abc import Callable, Iterator
from dataclasses import replace

from offprint.ir.model import (
    Block,
    Bold,
    Cite,
    Equation,
    Figure,
    Heading,
    Italic,
    Link,
    ListItem,
    Paragraph,
    Reference,
    Run,
    Runs,
    Sub,
    Sup,
    Table,
)

type RunMapper = Callable[[Run], Runs]

_CONTAINERS = (Italic, Bold, Sup, Sub, Link, Cite)


def map_runs(runs: Runs, mapper: RunMapper) -> Runs:
    """Replace each leaf run with what `mapper` returns, keeping the runs around it."""
    mapped: list[Run] = []
    for run in runs:
        if isinstance(run, _CONTAINERS):
            mapped.append(replace(run, runs=map_runs(run.runs, mapper)))
        else:
            mapped.extend(mapper(run))
    return tuple(mapped)


def map_block_runs[B: Block](block: B, mapper: RunMapper) -> B:
    """Apply `map_runs` to everything in `block` that holds runs."""

    def mapped(runs: Runs) -> Runs:
        return map_runs(runs, mapper)

    match block:
        case Heading() | Paragraph() | ListItem() | Reference():
            return replace(block, runs=mapped(block.runs))
        case Figure():
            return replace(block, caption=mapped(block.caption))
        case Table():
            return replace(
                block,
                caption=mapped(block.caption),
                header=tuple(mapped(cell) for cell in block.header),
                rows=tuple(tuple(mapped(cell) for cell in row) for row in block.rows),
                notes=mapped(block.notes),
            )
        case Equation():
            return block


def iter_runs(block: Block) -> Iterator[Run]:
    """Yield the leaf runs in `block`, in order."""
    leaves: list[Run] = []

    def collect(run: Run) -> Runs:
        leaves.append(run)
        return (run,)

    map_block_runs(block, collect)
    return iter(leaves)
