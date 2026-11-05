"""What resolving an input produces."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from offprint.ir import Meta, SourceTier

type Status = Literal["chosen", "available", "unavailable", "skipped", "failed"]
type LookupStatus = Literal["ok", "missing", "skipped", "failed"]

TIERS: tuple[SourceTier, ...] = ("latex", "jats", "pdf", "ml")


@dataclass(frozen=True, slots=True)
class Attempt:
    """One source in one tier, and what happened to it. `url` is set if a URL was found."""

    tier: SourceTier
    source: str
    status: Status
    reason: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Lookup:
    """One metadata service."""

    service: str
    status: LookupStatus
    reason: str


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome for one input. `path` and `tier` are `None` if no source could be obtained."""

    input: str
    attempts: tuple[Attempt, ...]
    lookups: tuple[Lookup, ...] = ()
    meta: Meta | None = None
    path: Path | None = None
    tier: SourceTier | None = None
    from_cache: bool = False
