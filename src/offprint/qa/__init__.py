"""QA gate: checks, report and verdict (#6). A book that fails goes to review, not to the Kindle.

See `docs/qa.md` for the checks and the format of `qa.json`.
"""

from offprint.qa.catalog import CHECKS, Check
from offprint.qa.config import QaConfig, load_config
from offprint.qa.gate import run_gate
from offprint.qa.model import CheckResult, Counts, Finding, QaReport
from offprint.qa.report import (
    QA_SCHEMA_VERSION,
    summary,
    to_data,
    to_json,
    to_markdown,
    write_report,
)

__all__ = [
    "CHECKS",
    "QA_SCHEMA_VERSION",
    "Check",
    "CheckResult",
    "Counts",
    "Finding",
    "QaConfig",
    "QaReport",
    "load_config",
    "run_gate",
    "summary",
    "to_data",
    "to_json",
    "to_markdown",
    "write_report",
]
