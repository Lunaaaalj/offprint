"""Find display equations among text blocks and group the pieces of each one."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from offprint.adapters.pdf.layout import Column, column_range
from offprint.adapters.pdf.roles import block_text, first_span
from offprint.cleanup import clean_text
from offprint.cleanup.geometry import union
from offprint.extraction import Line, Span, TextBlock
from offprint.ir import BBox
from offprint.profiles.schema import Profile


@dataclass(frozen=True, slots=True, kw_only=True)
class EquationPiece:
    block: TextBlock
    column: Column


@dataclass(frozen=True, slots=True, kw_only=True)
class DisplayEquation:
    column: Column
    bbox: BBox
    """The crop: as wide as the column, so the number stays in the picture."""
    alt: str
    number: str | None
    page: int


def _spans(block: TextBlock) -> list[Span]:
    return [span for line in block.lines for span in line.spans if span.text.strip()]


def _line_text(line: Line) -> str:
    return clean_text("".join(span.text for span in line.spans))


def _has_number(block: TextBlock, right_edge: float, profile: Profile) -> bool:
    equations = profile.equations
    for line in block.lines:
        at_edge = line.bbox[2] > right_edge - equations.right_edge_tolerance
        if at_edge and re.search(equations.trailing_number, _line_text(line)):
            return True
        for span in line.spans:
            if re.search(equations.number, clean_text(span.text).strip()):
                return True
    return False


def is_display_equation(block: TextBlock, column: Column, profile: Profile) -> bool:
    """Detect a piece of display math: a number at the edge, a math font or a centred formula."""
    equations = profile.equations
    measured = "left" if column == "full" else column
    left, right = column_range(measured, profile.page)
    first = first_span(block)
    if first is None:
        return False
    if len(block.lines) <= equations.max_numbered_lines and _has_number(block, right, profile):
        return True
    if any(span.font.startswith(tuple(equations.math_fonts)) for span in _spans(block)):
        return True
    text = block_text(block)
    centred = (
        block.bbox[0] > left + equations.centred_indent
        and len(block.lines) <= equations.max_centred_lines
        and re.search(profile.text.bullet, text) is None
    )
    return centred and first.size >= equations.centred_min_size and equations.centred_marker in text


def _pop_number(line: Line, profile: Profile) -> tuple[str | None, str]:
    """Split a line into its equation number, if it has one, and the rest of its text."""
    equations = profile.equations
    for index, span in enumerate(line.spans):
        found = re.search(equations.number, clean_text(span.text).strip())
        if found is not None:
            rest = line.spans[:index] + line.spans[index + 1 :]
            return found["number"], clean_text("".join(s.text for s in rest)).strip()
    text = _line_text(line).strip()
    found = re.search(equations.trailing_number, text)
    if found is not None:
        return found["number"], text[: found.start()].strip()
    return None, text


def _build(group: Sequence[EquationPiece], profile: Profile) -> DisplayEquation:
    equations = profile.equations
    column = group[0].column
    left, right = column_range(column, profile.page)
    top = min(piece.block.bbox[1] for piece in group) - equations.crop_margin
    bottom = max(piece.block.bbox[3] for piece in group) + equations.crop_margin

    # The alt keeps the PDF's own order: sorting by position scrambles sub- and superscripts.
    number = None
    words = []
    for piece in group:
        for line in piece.block.lines:
            found, text = _pop_number(line, profile)
            number = number or found
            if text:
                words.append(text)
    return DisplayEquation(
        column=column,
        bbox=(left, top, right, bottom),
        alt=" ".join(words),
        number=number,
        page=group[0].block.page,
    )


def group_equations(
    pieces: Sequence[EquationPiece], profile: Profile
) -> tuple[DisplayEquation, ...]:
    """Merge pieces close together in one column: fractions and sums come in several blocks."""
    ordered = sorted(pieces, key=lambda piece: (piece.column, piece.block.bbox[1]))
    groups: list[list[EquationPiece]] = []
    for piece in ordered:
        last = groups[-1] if groups else None
        if (
            last is not None
            and last[-1].column == piece.column
            and piece.block.bbox[1] - union(p.block.bbox for p in last)[3]
            < profile.equations.merge_gap
        ):
            last.append(piece)
        else:
            groups.append([piece])
    return tuple(_build(group, profile) for group in groups)
