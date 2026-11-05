"""The IR's types: frozen dataclasses, so cleanup steps stay pure (`dataclasses.replace`).

Sequences are tuples. Numbers are strings because real papers have "S1", "A.2" and "12a".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type Run = Text | Italic | Bold | Sup | Sub | Link | Cite | MathInline
type Runs = tuple[Run, ...]
type Cell = Runs
type Block = Heading | Paragraph | ListItem | Equation | Figure | Table | Reference
type ParagraphRole = Literal["body", "abstract", "small", "meta"]
type SourceTier = Literal["latex", "jats", "pdf", "ml"]
type BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Text:
    text: str


@dataclass(frozen=True, slots=True)
class Italic:
    runs: Runs


@dataclass(frozen=True, slots=True)
class Bold:
    runs: Runs


@dataclass(frozen=True, slots=True)
class Sup:
    runs: Runs


@dataclass(frozen=True, slots=True)
class Sub:
    runs: Runs


@dataclass(frozen=True, slots=True)
class Link:
    href: str
    runs: Runs


@dataclass(frozen=True, slots=True)
class Cite:
    target: str
    runs: Runs


@dataclass(frozen=True, slots=True)
class MathInline:
    text: str
    latex: str | None = None
    asset: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Heading:
    id: str
    level: int
    runs: Runs
    number: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Paragraph:
    id: str
    runs: Runs
    role: ParagraphRole = "body"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListItem:
    id: str
    runs: Runs
    ordered: bool = False
    depth: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Equation:
    id: str
    alt: str
    number: str | None = None
    latex: str | None = None
    asset: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Figure:
    id: str
    number: str
    asset: str
    caption: Runs
    alt: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Table:
    id: str
    number: str
    caption: Runs
    header: tuple[Cell, ...]
    rows: tuple[tuple[Cell, ...], ...]
    notes: Runs = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Reference:
    id: str
    runs: Runs
    key: str | None = None
    doi: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Author:
    name: str
    affiliation: str | None = None
    corresponding: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class License:
    spdx: str
    holder: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Meta:
    title: str
    authors: tuple[Author, ...] = ()
    journal: str | None = None
    year: int | None = None
    volume: str | None = None
    article_id: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    license: License | None = None
    abstract: Runs = ()
    keywords: tuple[str, ...] = ()
    source_tier: SourceTier | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MathBox:
    """A rendered formula's size in em. `depth` is how far it reaches below the text baseline."""

    width: float
    height: float
    depth: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Asset:
    id: str
    mime: str
    bytes: bytes = field(repr=False)
    width: int | None = None
    height: int | None = None
    box: MathBox | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    adapter: str
    page: int | None = None
    bbox: BBox | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Document:
    meta: Meta
    blocks: tuple[Block, ...] = ()
    assets: dict[str, Asset] = field(default_factory=dict)
    provenance: dict[str, Provenance] = field(default_factory=dict)
