"""Write a report: `qa.json` for machines, `qa.md` for people, a summary for the terminal.

The format of `qa.json` is documented in `docs/qa.md`, and later stages rely on it. Adding a key is
fine. Changing or removing one means raising `QA_SCHEMA_VERSION`.
"""

import json
from pathlib import Path
from typing import Any

from offprint.qa.catalog import BY_ID
from offprint.qa.model import CheckResult, Finding, QaReport

QA_SCHEMA_VERSION = 1


def _finding_data(finding: Finding) -> dict[str, Any]:
    location = finding.location
    return {
        "check": finding.check,
        "severity": finding.severity,
        "message": finding.message,
        "hint": BY_ID[finding.check].hint,
        "block_id": finding.block_id,
        "page": finding.page,
        "bbox": list(finding.bbox) if finding.bbox else None,
        "location": {"file": location.file, "fragment": location.fragment} if location else None,
    }


def _check_data(result: CheckResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "severity": result.severity,
        "status": result.status,
        "findings": result.findings,
        "value": result.value,
        "threshold": result.threshold,
        "reason": result.reason,
    }


def _totals(report: QaReport) -> dict[str, int]:
    statuses = [result.status for result in report.checks]
    return {status: statuses.count(status) for status in ("pass", "warn", "fail", "skip")}


def to_data(report: QaReport) -> dict[str, Any]:
    counts = report.counts
    return {
        "schema_version": QA_SCHEMA_VERSION,
        "verdict": report.verdict,
        "score": report.score,
        "title": report.title,
        "epub": report.epub,
        "counts": {
            "pages": counts.pages,
            "figures": counts.figures,
            "tables": counts.tables,
            "equations": counts.equations,
            "sections": counts.sections,
        },
        "totals": _totals(report),
        "checks": [_check_data(result) for result in report.checks],
        "findings": [_finding_data(finding) for finding in report.findings],
    }


def to_json(report: QaReport) -> str:
    return json.dumps(to_data(report), indent=2, ensure_ascii=False) + "\n"


def _place(finding: Finding) -> str:
    parts = []
    if finding.page is not None:
        parts.append(f"page {finding.page}")
    if finding.location is not None:
        fragment = f"#{finding.location.fragment}" if finding.location.fragment else ""
        parts.append(f"{finding.location.file}{fragment}")
    return f" ({', '.join(parts)})" if parts else ""


def _value(result: CheckResult) -> str:
    if result.threshold is not None and result.value is not None:
        return f"{result.value:.3f} (needs {result.threshold:.3f})"
    return ""


def _findings_section(title: str, findings: list[Finding]) -> list[str]:
    if not findings:
        return []
    lines = [f"## {title}", ""]
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.check, []).append(finding)
    for check, group in groups.items():
        lines += [f"### {check}", "", BY_ID[check].hint, ""]
        lines += [f"- {finding.message}{_place(finding)}" for finding in group]
        lines.append("")
    return lines


def _table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: QaReport) -> str:
    """Write a report that can be read on its own: what failed, where and what to try."""
    totals = _totals(report)
    counts = report.counts
    pages = "?" if counts.pages is None else counts.pages
    lines = [
        f"# QA report: {report.title or 'Untitled'}",
        "",
        f"**Verdict: {report.verdict}** (score {report.score:.3f}).",
        "",
        f"{totals['fail']} failed, {totals['warn']} with warnings, {totals['skip']} skipped and "
        f"{totals['pass']} passed, out of {len(report.checks)} checks.",
        "",
        f"The source has {pages} pages. The book has {counts.figures} figures, {counts.tables} "
        f"tables, {counts.equations} numbered equations and {counts.sections} sections.",
        "",
    ]
    if report.epub:
        lines += [f"Book: `{report.epub}`. Page numbers below are the source's.", ""]
    lines += _findings_section(
        "Errors", [finding for finding in report.findings if finding.severity == "error"]
    )
    lines += _findings_section(
        "Warnings", [finding for finding in report.findings if finding.severity == "warn"]
    )
    skipped = [result for result in report.checks if result.status == "skip"]
    if skipped:
        lines += ["## Skipped", ""]
        lines += [f"- {result.id}: {result.reason}" for result in skipped]
        lines.append("")
    lines += ["## All checks", "", "| Check | Status | Findings | Value |", "|---|---|---|---|"]
    lines += [
        f"| {result.id} | {result.status} | {result.findings} | {_table_cell(_value(result))} |"
        for result in report.checks
    ]
    return "\n".join(lines) + "\n"


def _summary_line(findings: list[Finding]) -> str:
    first = findings[0]
    more = f" (and {len(findings) - 1} more)" if len(findings) > 1 else ""
    return f"  {first.severity} {first.check}: {first.message}{_place(first)}{more}"


def summary(report: QaReport, report_path: Path) -> str:
    """Return one screen for the terminal: a line per check that found something, errors first."""
    totals = _totals(report)
    lines = [
        f"QA {report.verdict}: score {report.score:.3f}, {totals['fail']} failed, "
        f"{totals['warn']} with warnings, {totals['skip']} skipped of {len(report.checks)} checks"
    ]
    coverage = report.check("coverage.words")
    if coverage.value is not None:
        lines.append(f"  coverage.words {_value(coverage)}")
    groups: dict[str, list[Finding]] = {}
    for finding in sorted(report.findings, key=lambda finding: finding.severity != "error"):
        groups.setdefault(finding.check, []).append(finding)
    lines += [_summary_line(group) for group in groups.values()]
    lines += [
        f"  skipped {result.id}: {result.reason}"
        for result in report.checks
        if result.status == "skip" and not result.id.startswith("cover.")
    ]
    lines.append(f"Details: {report_path}")
    return "\n".join(lines)


def write_report(report: QaReport, outdir: Path, stem: str) -> tuple[Path, Path]:
    """Write `<stem>.qa.json` and `<stem>.qa.md`, next to the book, and return their paths."""
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / f"{stem}.qa.json"
    markdown_path = outdir / f"{stem}.qa.md"
    json_path.write_text(to_json(report), encoding="utf-8")
    markdown_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, markdown_path
