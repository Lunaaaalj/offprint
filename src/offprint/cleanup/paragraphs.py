"""Paragraph joining: undo the breaks that columns and pages put in the middle of a sentence."""

import re
from dataclasses import dataclass, replace

from offprint.cleanup.registry import step
from offprint.cleanup.runs import join_runs, plain_text
from offprint.cleanup.text import KeepHyphen
from offprint.ir import Block, Document, Figure, Paragraph, ParagraphRole, Provenance, Table


@dataclass(frozen=True, slots=True, kw_only=True)
class ParagraphOptions:
    terminator: str = r"[.:?!]\)?[”\"]?$"
    """A paragraph whose text matches this regex is finished."""
    loose_roles: tuple[ParagraphRole, ...] = ()
    """In these roles an unfinished paragraph absorbs the next even if it doesn't start lowercase.
    Use it where roles are reliable enough that same-role text always continues the sentence."""
    starts_new: str | None = None
    """A paragraph whose text matches this regex is never absorbed, such as a list bullet."""
    keep_hyphen: KeepHyphen | None = None


def _continues(previous: Paragraph, block: Paragraph, options: ParagraphOptions) -> bool:
    if previous.role != block.role:
        return False
    before = plain_text(previous.runs).strip()
    after = plain_text(block.runs).strip()
    if not before or not after or re.search(options.terminator, before):
        return False
    if options.starts_new is not None and re.search(options.starts_new, after):
        return False
    return after[0].islower() or block.role in options.loose_roles


def _last_non_float(blocks: list[Block]) -> int | None:
    for index in range(len(blocks) - 1, -1, -1):
        if not isinstance(blocks[index], Figure | Table):
            return index
    return None


@step("join_paragraphs", "paragraph")
def join_paragraphs(doc: Document, options: ParagraphOptions | None = None) -> Document:
    """Merge a paragraph into the unfinished one before it.

    Figures and tables between the two stay put, so they end up after the merged paragraph.
    Headings, lists and equations stop a merge: nothing joins across an equation. The result keeps
    the first block's id and provenance, and the provenance note names the blocks it absorbed.
    """
    options = options or ParagraphOptions()
    blocks: list[Block] = []
    provenance = dict(doc.provenance)
    for block in doc.blocks:
        target = _last_non_float(blocks)
        previous = blocks[target] if target is not None else None
        if (
            target is not None
            and isinstance(block, Paragraph)
            and isinstance(previous, Paragraph)
            and _continues(previous, block, options)
        ):
            runs = join_runs(previous.runs, block.runs, options.keep_hyphen)
            blocks[target] = replace(previous, runs=runs)
            provenance.pop(block.id, None)
            if previous.id in provenance:
                provenance[previous.id] = _note_join(provenance[previous.id], block.id)
        else:
            blocks.append(block)
    return replace(doc, blocks=tuple(blocks), provenance=provenance)


def _note_join(provenance: Provenance, block_id: str) -> Provenance:
    note = f"{provenance.note}, {block_id}" if provenance.note else f"joined {block_id}"
    return replace(provenance, note=note)
