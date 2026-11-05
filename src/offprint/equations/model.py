"""What the equation stage passes around."""

from dataclasses import dataclass

from offprint.ir import Document, MathBox, Problem

_EM_DIGITS = 4


class MathRenderError(Exception):
    """This formula can't be rendered. The message says why, in TeX's words when it can."""


@dataclass(frozen=True, slots=True)
class MathSettings:
    """What shapes the images. Every field goes in the cache key."""

    # 14.4pt at 300 ppi, so a reader's larger type setting doesn't have to upscale the image.
    px_per_em: int = 60


@dataclass(frozen=True, slots=True)
class MathRequest:
    """One distinct formula. Inline and display are different typesetting of the same LaTeX."""

    latex: str
    display: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedMath:
    png: bytes
    width: int
    height: int
    box: MathBox
    system_font: bool = False


@dataclass(frozen=True, slots=True)
class TypesetResult:
    doc: Document
    problems: tuple[Problem, ...] = ()


def round_em(value: float) -> float:
    """Round a length in em, so the metrics read the same however they were computed. Pure."""
    return round(value, _EM_DIGITS)
