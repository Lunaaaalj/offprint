"""Smoke tests for the command-line interface."""

from importlib.metadata import version

from typer.testing import CliRunner

from offprint.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"offprint {version('offprint')}"


def test_preview_is_not_implemented_yet() -> None:
    result = runner.invoke(app, ["preview", "paper.epub"])

    assert result.exit_code == 1
    assert "offprint preview: not implemented" in result.stderr
