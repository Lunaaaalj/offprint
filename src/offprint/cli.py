"""Command-line interface: parses arguments and hands off to the pipeline stages."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from offprint import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Turn research papers into clean, reflowable Kindle books.",
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"offprint {__version__}")
        raise typer.Exit()


def _not_implemented(command: str, issues: str) -> NoReturn:
    typer.echo(f"offprint {command}: not implemented yet (see {issues}).", err=True)
    raise typer.Exit(code=1)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Turn research papers into clean, reflowable Kindle books."""


@app.command()
def convert(
    # A string, not a Path: the resolver (#9) will also accept DOIs and arXiv ids here.
    source: Annotated[str, typer.Argument(metavar="INPUT", help="The paper to convert.")],
    outdir: Annotated[
        Path, typer.Option("--output", "-o", metavar="OUTDIR", help="Where to write the EPUB.")
    ] = Path("."),
) -> None:
    """Convert a paper into an EPUB."""
    _not_implemented("convert", "#3 and #5")


@app.command()
def preview(
    epub: Annotated[Path, typer.Argument(metavar="EPUB", help="The EPUB to preview.")],
) -> None:
    """Render Kindle-sized page previews of an EPUB."""
    _not_implemented("preview", "#7")
