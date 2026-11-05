"""`offprint resolve`, replaying recordings through the real command."""

from collections.abc import Callable
from pathlib import Path

import pytest
from replay_support import CONTACT, Replay, no_wait
from typer.testing import CliRunner

from offprint.cli import app
from offprint.sources.http import Http

runner = CliRunner()
ReplayFactory = Callable[[str], Replay]


@pytest.fixture
def use_recording(
    replay: ReplayFactory, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], Replay]:
    def install(scenario: str) -> Replay:
        transport = replay(scenario)
        monkeypatch.setenv("OFFPRINT_CONTACT_EMAIL", CONTACT)
        monkeypatch.setattr(
            "offprint.sources.resolver.Http",
            lambda contact: Http(contact, transport=transport, limiter=no_wait()),
        )
        return transport

    return install


def test_resolve_prints_the_tiers_and_the_choice(
    use_recording: Callable[[str], Replay],
) -> None:
    transport = use_recording("arxiv-only")

    result = runner.invoke(app, ["resolve", "2610.22829"])

    assert result.exit_code == 0, result.output
    assert transport.unused == []
    assert "title: KKM meets colorful Carathéodory" in result.stdout
    assert "tier 1 (latex):" in result.stdout
    assert "arXiv e-print: chosen" in result.stdout
    assert "Europe PMC: unavailable: no DOI to search PubMed Central with" in result.stdout
    assert "choice: tier 1 (latex)" in result.stdout


def test_resolve_twice_stays_offline(use_recording: Callable[[str], Replay]) -> None:
    use_recording("arxiv-only")
    assert runner.invoke(app, ["resolve", "2610.22829"]).exit_code == 0

    transport = use_recording("arxiv-only")
    result = runner.invoke(app, ["resolve", "2610.22829"])

    assert result.exit_code == 0
    assert transport.requests == []
    assert "from the cache" in result.stdout


def test_resolve_exits_nonzero_when_nothing_is_found(
    use_recording: Callable[[str], Replay],
) -> None:
    use_recording("arxiv-missing")

    result = runner.invoke(app, ["resolve", "2601.99999"])

    assert result.exit_code == 1
    assert "choice: none" in result.stdout


def test_resolve_refuses_a_malformed_id() -> None:
    result = runner.invoke(app, ["resolve", "2413.01234"])

    assert result.exit_code == 1
    assert "offprint resolve: " in result.stderr
    assert "month 13" in result.stderr


def test_resolve_a_local_file(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7")

    result = runner.invoke(app, ["resolve", str(path)])

    assert result.exit_code == 0
    assert "choice: tier 3 (pdf)" in result.stdout


def test_resolve_reports_a_broken_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFPRINT_CONTACT_EMAIL", "not-an-address")

    result = runner.invoke(app, ["resolve", "2610.22829"])

    assert result.exit_code == 1
    assert "isn't an email" in result.stderr
