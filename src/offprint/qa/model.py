"""What the gate produces: findings, a result per check, and the report that holds them."""

from dataclasses import dataclass
from typing import Literal

from offprint.ir import BBox
from offprint.render.epub import BookLocation

type Severity = Literal["error", "warn"]
type Status = Literal["pass", "warn", "fail", "skip"]
type Verdict = Literal["pass", "review"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """One thing wrong. `page` and `bbox` point into the source and `location` into the EPUB."""

    check: str
    message: str
    severity: Severity
    block_id: str | None = None
    page: int | None = None
    bbox: BBox | None = None
    location: BookLocation | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Outcome:
    """What running a check found. `skipped` says why it couldn't run."""

    findings: tuple[Finding, ...] = ()
    skipped: str | None = None
    value: float | None = None
    threshold: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckResult:
    id: str
    severity: Severity
    status: Status
    hint: str
    findings: int = 0
    reason: str | None = None
    value: float | None = None
    threshold: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Counts:
    pages: int | None
    figures: int
    tables: int
    equations: int
    sections: int


@dataclass(frozen=True, slots=True, kw_only=True)
class QaReport:
    title: str
    epub: str | None
    verdict: Verdict
    score: float
    counts: Counts
    checks: tuple[CheckResult, ...]
    findings: tuple[Finding, ...]

    def check(self, check_id: str) -> CheckResult:
        return next(result for result in self.checks if result.id == check_id)
