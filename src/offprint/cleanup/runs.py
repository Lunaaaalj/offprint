"""Helpers for working with IR runs. They hold no judgement, so they aren't cleanup steps."""

from dataclasses import replace

from offprint.cleanup.text import KeepHyphen, hyphen_break
from offprint.ir import MathInline, Run, Runs, Text


def plain_text(runs: Runs) -> str:
    return "".join(_run_text(run) for run in runs)


def _run_text(run: Run) -> str:
    if isinstance(run, Text | MathInline):
        return run.text
    return plain_text(run.runs)


def _ends_in_text(runs: Runs) -> bool:
    if not runs:
        return False
    last = runs[-1]
    if isinstance(last, MathInline):
        return False
    return isinstance(last, Text) or _ends_in_text(last.runs)


def _without_last_character(runs: Runs) -> Runs:
    last = runs[-1]
    if isinstance(last, Text):
        shorter: Runs = (Text(last.text[:-1]),) if len(last.text) > 1 else ()
    elif isinstance(last, MathInline):
        return runs
    else:
        shorter = (replace(last, runs=_without_last_character(last.runs)),)
    return runs[:-1] + shorter


def join_runs(left: Runs, right: Runs, keep_hyphen: KeepHyphen | None = None) -> Runs:
    """Join two pieces of a sentence that a line, column or page break separated."""
    if not left or not right:
        return left + right
    how = hyphen_break(plain_text(left), plain_text(right), keep_hyphen)
    if how == "join" and _ends_in_text(left):
        return _coalesce(_without_last_character(left) + right)
    if how == "keep":
        return _coalesce(left + right)
    return _coalesce((*left, Text(" "), *right))


def _coalesce(runs: Runs) -> Runs:
    joined: list[Run] = []
    for run in runs:
        previous = joined[-1] if joined else None
        if isinstance(run, Text) and isinstance(previous, Text):
            joined[-1] = Text(previous.text + run.text)
        else:
            joined.append(run)
    return tuple(joined)
