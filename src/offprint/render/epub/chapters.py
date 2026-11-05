"""Split the block list into chapters and derive the table of contents from them."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from offprint.ir import Block, Heading, Text
from offprint.render.epub.xhtml import plain_text

FRONT_MATTER_FILE = "front-matter.xhtml"


@dataclass(frozen=True, slots=True)
class Chapter:
    filename: str
    label: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class TocEntry:
    label: str
    href: str
    children: tuple["TocEntry", ...] = ()


def split_chapters(blocks: Sequence[Block]) -> tuple[tuple[Block, ...], tuple[Chapter, ...]]:
    """Return the blocks before the first top-level heading, and one chapter per such heading."""
    starts = [
        index
        for index, block in enumerate(blocks)
        if isinstance(block, Heading) and block.level == 1
    ]
    if not starts:
        return tuple(blocks), ()
    chapters = []
    for number, (start, end) in enumerate(pairwise([*starts, len(blocks)]), start=1):
        section = tuple(blocks[start:end])
        filename = f"chapter-{number:02}.xhtml"
        chapters.append(Chapter(filename, heading_label(blocks[start], number), section))
    return tuple(blocks[: starts[0]]), tuple(chapters)


def build_toc(chapters: Sequence[Chapter], anchors: Mapping[str, str]) -> tuple[TocEntry, ...]:
    """Return a two-level TOC: each chapter, with its level-2 headings beneath it.

    The front matter isn't listed: the reader opens on it, and the TOC is the paper's sections.
    """
    entries = []
    for chapter in chapters:
        subsections = [
            block for block in chapter.blocks if isinstance(block, Heading) and block.level == 2
        ]
        children = tuple(
            TocEntry(heading_label(heading, number), f"{chapter.filename}#{anchors[heading.id]}")
            for number, heading in enumerate(subsections, start=1)
        )
        href = f"{chapter.filename}#{anchors[chapter.blocks[0].id]}"
        entries.append(TocEntry(chapter.label, href, children))
    return tuple(entries)


def heading_label(heading: Heading, position: int) -> str:
    """Return a heading's TOC text. A TOC entry can't be blank, so an empty heading gets one."""
    parts = [plain_text((Text(heading.number or ""),)), plain_text(heading.runs)]
    return " ".join(part for part in parts if part) or f"Section {position}"
