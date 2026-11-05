"""Command-line interface: parses arguments and hands off to the pipeline stages."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from offprint import __version__, sources

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


def _emit_ir(source: Path, outdir: Path) -> None:
    # Imported here so that `--version` and `--help` don't pay for loading PyMuPDF.
    from offprint.adapters.pdf import LayoutError, NoProfileMatch, emit_ir

    if not source.is_file():
        typer.echo(f"offprint convert: no such file: {source}", err=True)
        raise typer.Exit(code=1)
    try:
        target = emit_ir(source, outdir)
    except (LayoutError, NoProfileMatch) as error:
        typer.echo(f"offprint convert: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(target)


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
    emit_ir: Annotated[
        bool, typer.Option("--emit-ir", help="Write the IR as JSON instead of an EPUB.")
    ] = False,
) -> None:
    """Convert a paper into an EPUB."""
    if emit_ir:
        _emit_ir(Path(source), outdir)
        return
    _not_implemented("convert", "#3 and #5")


@app.command()
def preview(
    epub: Annotated[Path, typer.Argument(metavar="EPUB", help="The EPUB to preview.")],
) -> None:
    """Render Kindle-sized page previews of an EPUB."""
    _not_implemented("preview", "#7")


@app.command()
def resolve(
    source: Annotated[
        str, typer.Argument(metavar="ID", help="A DOI, an arXiv id or URL, or a local file.")
    ],
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Look everything up again, ignoring the cache.")
    ] = False,
) -> None:
    """Find the best source for a paper, cache it, and explain the choice. Doesn't convert."""
    try:
        resolution = sources.resolve(source, refresh=refresh)
    except sources.SourceError as error:
        typer.echo(f"offprint resolve: {error}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(sources.format_report(resolution))
    if resolution.path is None:
        raise typer.Exit(code=1)
