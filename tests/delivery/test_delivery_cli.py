"""`offprint send` and `offprint convert --send`, through the command line."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from delivery_support import Inbox
from typer.testing import CliRunner

from offprint import pipeline, qa
from offprint.cli import app

CONFIG = """
[kindle]
address = "me_abc@kindle.com"
sender = "me@example.com"

[smtp]
host = "{host}"
port = {port}
security = "none"
"""


@pytest.fixture
def env(tmp_path: Path, inbox: Inbox) -> dict[str, str]:
    config = tmp_path / "config.toml"
    config.write_text(CONFIG.format(host=inbox.host, port=inbox.port), encoding="utf-8")
    return {
        "HOME": str(tmp_path),
        "OFFPRINT_CONFIG_FILE": str(config),
        "OFFPRINT_DELIVERY_LOG": str(tmp_path / "log.jsonl"),
    }


def report(epub: Path, verdict: str) -> None:
    epub.with_suffix(".qa.json").write_text(json.dumps({"verdict": verdict}), encoding="utf-8")


def squeezed(text: str) -> str:
    """Typer boxes and colours its usage errors, and wraps them. Compare without any of that."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return "".join(char for char in plain if char.isalnum() or char in "-_")


def run(args: list[str], env: dict[str, str]):
    return CliRunner().invoke(app, args, env=env)


# offprint send


def test_send_delivers_a_book_that_passed(epub: Path, env, inbox: Inbox) -> None:
    report(epub, "pass")

    result = run(["send", str(epub)], env)

    assert result.exit_code == 0, result.stderr
    assert "sent paper.epub to me_abc@kindle.com" in result.stderr
    assert len(inbox.envelopes) == 1


def test_send_refuses_a_book_in_review_with_exit_3(epub: Path, env, inbox: Inbox) -> None:
    report(epub, "review")

    result = run(["send", str(epub)], env)

    assert result.exit_code == 3
    assert "--force" in result.stderr
    assert inbox.envelopes == []


def test_send_force_sends_it(epub: Path, env, inbox: Inbox) -> None:
    report(epub, "review")

    result = run(["send", str(epub), "--force"], env)

    assert result.exit_code == 0, result.stderr
    assert len(inbox.envelopes) == 1


def test_send_without_a_report_counts_as_not_passed(epub: Path, env, inbox: Inbox) -> None:
    result = run(["send", str(epub)], env)

    assert result.exit_code == 3
    assert "unknown" in result.stderr


def test_send_reads_the_report_from_qa(epub: Path, env, tmp_path: Path, inbox: Inbox) -> None:
    elsewhere = tmp_path / "other.json"
    elsewhere.write_text('{"verdict": "pass"}', encoding="utf-8")

    result = run(["send", str(epub), "--qa", str(elsewhere)], env)

    assert result.exit_code == 0, result.stderr


def test_send_dry_run_writes_the_eml(epub: Path, env, inbox: Inbox) -> None:
    report(epub, "pass")

    result = run(["send", str(epub), "--dry-run"], env)

    assert result.exit_code == 0, result.stderr
    assert epub.with_suffix(".eml").exists()
    assert "dry run" in result.stderr
    assert inbox.envelopes == []


def test_send_twice_is_refused_the_second_time(epub: Path, env, inbox: Inbox) -> None:
    report(epub, "pass")
    run(["send", str(epub)], env)

    result = run(["send", str(epub)], env)

    assert result.exit_code == 1
    assert "already sent" in result.stderr


def test_send_without_a_config_says_where_it_should_be(epub: Path, tmp_path: Path) -> None:
    report(epub, "pass")
    missing = {"HOME": str(tmp_path), "OFFPRINT_CONFIG_FILE": str(tmp_path / "none.toml")}

    result = run(["send", str(epub)], missing)

    assert result.exit_code == 1
    assert "no config file at" in result.stderr


def test_send_reports_a_missing_book(tmp_path: Path, env) -> None:
    result = run(["send", str(tmp_path / "no.epub")], env)

    assert result.exit_code == 1
    assert "no such file" in result.stderr


# offprint convert --send


@pytest.fixture
def converted(monkeypatch: pytest.MonkeyPatch, epub: Path):
    """`convert` without PyMuPDF and Chromium: it returns `epub` with the verdict a test picks."""

    def make(verdict: str) -> None:
        conversion = SimpleNamespace(
            path=epub, report=SimpleNamespace(verdict=verdict), report_path=epub.with_suffix(".md")
        )
        monkeypatch.setattr(pipeline, "convert_to_epub", lambda *a, **k: conversion)
        monkeypatch.setattr(qa, "summary", lambda report, path: f"QA {report.verdict}")

    return make


def test_convert_send_delivers_a_passing_book(converted, env, inbox: Inbox) -> None:
    converted("pass")

    result = run(["convert", "paper.pdf", "--send"], env)

    assert result.exit_code == 0, result.stderr
    assert len(inbox.envelopes) == 1


def test_convert_send_keeps_exit_3_and_sends_nothing_for_review(converted, env, inbox) -> None:
    converted("review")

    result = run(["convert", "paper.pdf", "--send"], env)

    assert result.exit_code == 3
    assert "isn't sent" in result.stderr
    assert inbox.envelopes == []


def test_convert_send_force_sends_a_book_in_review(converted, env, inbox: Inbox) -> None:
    converted("review")

    result = run(["convert", "paper.pdf", "--send", "--force"], env)

    assert result.exit_code == 0, result.stderr
    assert len(inbox.envelopes) == 1


def test_allow_review_exits_0_but_still_does_not_send(converted, env, inbox: Inbox) -> None:
    converted("review")

    result = run(["convert", "paper.pdf", "--send", "--allow-review"], env)

    assert result.exit_code == 0
    assert "isn't sent" in result.stderr
    assert inbox.envelopes == []


def test_convert_send_dry_run_writes_the_eml(converted, env, epub: Path) -> None:
    converted("pass")

    result = run(["convert", "paper.pdf", "--send", "--dry-run"], env)

    assert result.exit_code == 0, result.stderr
    assert epub.with_suffix(".eml").exists()


def test_convert_without_send_never_touches_delivery(converted, tmp_path: Path, epub) -> None:
    converted("pass")

    result = run(["convert", "paper.pdf"], {"HOME": str(tmp_path)})

    assert result.exit_code == 0


@pytest.mark.parametrize("flag", ["--force", "--dry-run"])
def test_force_and_dry_run_need_send(flag: str, env) -> None:
    result = run(["convert", "paper.pdf", flag], env)

    assert result.exit_code == 2
    assert "--send" in squeezed(result.output + result.stderr)


def test_send_cannot_be_combined_with_emit_ir(env) -> None:
    result = run(["convert", "paper.pdf", "--emit-ir", "--send"], env)

    assert result.exit_code == 2
