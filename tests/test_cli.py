"""Smoke tests for the command-line interface."""

from importlib.metadata import version

import pytest
from typer.testing import CliRunner

from offprint.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"offprint {version('offprint')}"


@pytest.mark.parametrize(
    ("args", "command"),
    [
        (["convert", "paper.pdf"], "convert"),
        (["convert", "paper.pdf", "-o", "build/"], "convert"),
        (["preview", "paper.epub"], "preview"),
    ],
)
def test_unimplemented_commands_fail_loudly(args: list[str], command: str) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 1
    assert f"offprint {command}: not implemented" in result.stderr
