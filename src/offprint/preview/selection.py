"""Decide which pages to render, from a chapter-by-chapter measurement of the book. Pure."""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from offprint.qa import QA_SCHEMA_VERSION


class PreviewError(ValueError):
    """The preview can't be made, for a reason the user can act on."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Flag:
    """A QA finding's place in the book."""

    check: str
    file: str
    fragment: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChapterLayout:
    file: str
    pages: int
    cover: bool = False
    figure: int | None = None
    equation: int | None = None
    table: int | None = None
    anchors: Mapping[str, int] = field(default_factory=dict)
    """Page of each id that was asked about."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    file: str
    page: int
    """0-based, like every page number in this package but the ones people read."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedPage:
    file: str
    page: int
    reasons: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()


class _Selection:
    def __init__(self, layouts: Sequence[ChapterLayout]) -> None:
        self.order = {layout.file: index for index, layout in enumerate(layouts)}
        self.reasons: dict[tuple[str, int], list[str]] = {}
        self.checks: dict[tuple[str, int], list[str]] = {}

    def add(self, file: str, page: int, reason: str | None = None) -> None:
        reasons = self.reasons.setdefault((file, page), [])
        if reason is not None and reason not in reasons:
            reasons.append(reason)

    def flag(self, file: str, page: int, check: str) -> None:
        self.add(file, page)
        checks = self.checks.setdefault((file, page), [])
        if check not in checks:
            checks.append(check)

    def pages(self) -> tuple[SelectedPage, ...]:
        return tuple(
            SelectedPage(
                file=file,
                page=page,
                reasons=tuple(self.reasons[(file, page)]),
                checks=tuple(self.checks.get((file, page), ())),
            )
            for file, page in sorted(self.reasons, key=lambda at: (self.order[at[0]], at[1]))
        )


def automatic_selection(
    layouts: Sequence[ChapterLayout], flags: Iterable[Flag] = ()
) -> tuple[tuple[SelectedPage, ...], tuple[Flag, ...]]:
    """Pick the first page, the first page with each kind of block, and every flagged page.

    Returns the pages in reading order, and the flags with no page, whose file isn't in the book.
    """
    selection = _Selection(layouts)
    reading = [layout for layout in layouts if not layout.cover] or list(layouts)
    if reading:
        selection.add(reading[0].file, 0, "first page")
    for kind, reason in (
        ("figure", "first figure"),
        ("equation", "first equation"),
        ("table", "first table"),
    ):
        first = next((layout for layout in reading if getattr(layout, kind) is not None), None)
        if first is not None:
            selection.add(first.file, getattr(first, kind), reason)

    by_file = {layout.file: layout for layout in layouts}
    unplaced = []
    for flag in flags:
        layout = by_file.get(flag.file)
        if layout is None:
            unplaced.append(flag)
        else:
            selection.flag(flag.file, layout.anchors.get(flag.fragment, 0), flag.check)
    return selection.pages(), tuple(unplaced)


def requested_selection(
    requests: Sequence[PageRequest], layouts: Sequence[ChapterLayout]
) -> tuple[SelectedPage, ...]:
    """Check the pages the user named against the book, and put them in reading order."""
    selection = _Selection(layouts)
    by_file = {layout.file: layout for layout in layouts}
    for request in requests:
        layout = by_file[request.file]
        if request.page >= layout.pages:
            raise PreviewError(
                f"{request.file} has {layout.pages} pages, so there is no page {request.page + 1}"
            )
        selection.add(request.file, request.page, "requested")
    return selection.pages()


def parse_page(text: str, files: Sequence[str]) -> PageRequest:
    """Read `chapter:page`. The chapter is a file, its stem, or the number in `chapter-NN`.

    0 is the front matter, and pages count from 1.
    """
    found = re.fullmatch(r"(?P<chapter>.+):(?P<page>[1-9]\d*)", text.strip())
    if found is None:
        raise PreviewError(f"{text!r} isn't chapter:page, such as 3:2 or front-matter:1")
    chapter = found["chapter"]
    if chapter.isdecimal():
        chapter = f"chapter-{int(chapter):02}" if int(chapter) else "front-matter"
    for file in files:
        if chapter in (file, Path(file).stem):
            return PageRequest(file=file, page=int(found["page"]) - 1)
    raise PreviewError(f"the book has no chapter {found['chapter']!r} (it has {', '.join(files)})")


def read_flags(path: Path) -> tuple[tuple[Flag, ...], int]:
    """Read a `qa.json`. Returns the flags, and how many findings have no place in the book."""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PreviewError(f"can't read {path}: {error}") from error
    version = data.get("schema_version")
    if version != QA_SCHEMA_VERSION:
        raise PreviewError(f"{path} has schema version {version}, not {QA_SCHEMA_VERSION}")
    findings = data.get("findings", [])
    flags = tuple(
        Flag(
            check=finding["check"],
            file=finding["location"]["file"],
            fragment=finding["location"]["fragment"],
        )
        for finding in findings
        if finding.get("location")
    )
    return flags, len(findings) - len(flags)
