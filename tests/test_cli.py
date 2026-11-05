"""Smoke tests for the command-line interface."""

from importlib.metadata import version

from typer.testing import CliRunner

from offprint.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"offprint {version('offprint')}"


def test_preview_of_a_missing_file_fails_clearly() -> None:
    result = runner.invoke(app, ["preview", "paper.epub"])

    assert result.exit_code == 1
    assert "offprint preview: no such file" in result.stderr
