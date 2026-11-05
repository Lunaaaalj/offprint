"""Command-line interface: parses arguments and hands off to the pipeline stages."""

from pathlib import Path
from typing import Annotated

import typer

from offprint import __version__, sources

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Turn research papers into clean, reflowable Kindle books.",
)


# 1 means no book, 2 is a usage error, and this means the book exists but needs a human.
_REVIEW_EXIT_CODE = 3


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"offprint {__version__}")
        raise typer.Exit()


def _emit_ir(source: Path, outdir: Path) -> None:
    # Imported here so that `--version` and `--help` don't pay for loading PyMuPDF.
    from offprint.adapters.pdf import LayoutError, NoProfileMatch, UnreadablePdfError, emit_ir

    if not source.is_file():
        typer.echo(f"offprint convert: no such file: {source}", err=True)
        raise typer.Exit(code=1)
    try:
        target = emit_ir(source, outdir)
    except (LayoutError, NoProfileMatch, UnreadablePdfError) as error:
        typer.echo(f"offprint convert: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(target)


def _write_epub(source: str, outdir: Path, cover: bool, allow_review: bool) -> None:
    # Imported here so that `--version` and `--help` don't pay for PyMuPDF and Playwright.
    from offprint.pipeline import ConvertError, convert_to_epub
    from offprint.qa import summary

    try:
        result = convert_to_epub(source, outdir, cover=cover)
    except ConvertError as error:
        typer.echo(f"offprint convert: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(result.path)
    typer.echo(summary(result.report, result.report_path), err=True)
    if result.report.verdict == "review" and not allow_review:
        raise typer.Exit(code=_REVIEW_EXIT_CODE)


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
    # A string, not a Path: this can also be a DOI or an arXiv id.
    source: Annotated[
        str,
        typer.Argument(
            metavar="INPUT",
            help="A local PDF, or a DOI or arXiv id that `offprint resolve` has cached.",
        ),
    ],
    outdir: Annotated[
        Path, typer.Option("--output", "-o", metavar="OUTDIR", help="Where to write the EPUB.")
    ] = Path("."),
    emit_ir: Annotated[
        bool, typer.Option("--emit-ir", help="Write the IR as JSON instead of an EPUB.")
    ] = False,
    no_cover: Annotated[bool, typer.Option("--no-cover", help="Don't generate a cover.")] = False,
    allow_review: Annotated[
        bool, typer.Option("--allow-review", help="Exit 0 even if the QA verdict is review.")
    ] = False,
) -> None:
    """Convert a paper into an EPUB and check it. Never uses the network.

    Exits 1 if no book could be made and 3 if the book needs review (see `<name>.qa.md`).
    """
    if emit_ir:
        _emit_ir(Path(source), outdir)
        return
    _write_epub(source, outdir, cover=not no_cover, allow_review=allow_review)


@app.command()
def preview(
    epub: Annotated[Path, typer.Argument(metavar="EPUB", help="The EPUB to preview.")],
    outdir: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", metavar="OUTDIR", help="Where to write the pages [<stem>.preview]."
        ),
    ] = None,
    pages: Annotated[
        list[str] | None,
        typer.Option(
            "--pages",
            metavar="CHAPTER:PAGE",
            help="Render this page instead of the automatic selection. Can be repeated.",
        ),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option("--qa", metavar="QA_JSON", help="The QA report [<stem>.qa.json, if any]."),
    ] = None,
    bezel: Annotated[bool, typer.Option("--bezel", help="Draw a device around each page.")] = False,
    grayscale: Annotated[
        bool, typer.Option("--grayscale", help="Give each page an e-ink look.")
    ] = False,
) -> None:
    """Render Kindle-sized pages of an EPUB to PNGs, plus a contact sheet.

    By default: the first page, the first page with a figure, an equation and a table, and every
    page a QA check flagged.
    """
    # Imported here so that `--version` and `--help` don't pay for Playwright.
    from offprint.browser import BrowserUnavailableError
    from offprint.preview import PreviewError, PreviewOptions, link_report, preview_epub

    if not epub.is_file():
        typer.echo(f"offprint preview: no such file: {epub}", err=True)
        raise typer.Exit(code=1)
    options = PreviewOptions(
        pages=tuple(pages or ()), report=report, bezel=bezel, grayscale=grayscale
    )
    try:
        result = preview_epub(epub, outdir, options)
    except (PreviewError, BrowserUnavailableError, OSError) as error:
        typer.echo(f"offprint preview: {error}", err=True)
        raise typer.Exit(code=1) from error
    for page in result.pages:
        typer.echo(page.image)
    typer.echo(result.contact_sheet)
    linked = link_report(result)
    if linked is not None:
        typer.echo(f"Linked from {linked}", err=True)
    if result.unplaced:
        typer.echo(f"{result.unplaced} findings have no page in the book.", err=True)


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
