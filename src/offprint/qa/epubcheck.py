"""`epubcheck`: run the external validator on the finished book, when it's installed."""

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from offprint.qa.model import Finding, Outcome, Severity
from offprint.render.epub import BookLocation

_NOT_INSTALLED = "epubcheck isn't installed, so EPUB validity is unknown"
_SEVERITIES: Mapping[str, Severity] = {"FATAL": "error", "ERROR": "error", "WARNING": "warn"}


def _finding(message: Mapping[str, Any], severity: Severity, root: str) -> Finding:
    locations = message.get("locations") or [{}]
    where = locations[0]
    path = where.get("path")
    line = where.get("line", -1)
    place = f" ({path}:{line})" if path and line > 0 else ""
    name = path.removeprefix(f"{root}/") if path and root else path
    return Finding(
        check="epubcheck",
        message=f"{message.get('ID', '?')}: {message.get('message', '')}{place}",
        severity=severity,
        location=BookLocation(name) if name else None,
    )


def parse_report(report: Mapping[str, Any], root: str = "") -> tuple[Finding, ...]:
    """Turn epubcheck's JSON report into findings. `root` is the folder paths are relative to."""
    return tuple(
        _finding(message, _SEVERITIES[message["severity"]], root)
        for message in report.get("messages", ())
        if message.get("severity") in _SEVERITIES
    )


def run_epubcheck(path: Path, *, timeout: float, root: str = "") -> Outcome:
    """Validate an EPUB. Without epubcheck installed, the report says it was skipped."""
    executable = shutil.which("epubcheck")
    if executable is None:
        return Outcome(skipped=_NOT_INSTALLED)
    try:
        done = subprocess.run(
            [executable, str(path), "--json", "-"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Outcome(skipped=f"epubcheck didn't finish: {error}")
    try:
        return Outcome(findings=parse_report(_report_json(done.stdout), root))
    except ValueError as error:
        return Outcome(skipped=f"can't read epubcheck's report: {error}")


def _report_json(output: str) -> dict[str, Any]:
    """Read the report from epubcheck's stdout, which can have log lines before the JSON."""
    return json.loads(output[output.index("{") :])
