"""Command-line interface: parses arguments and hands off to the pipeline stages."""

from dataclasses import dataclass
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


def _emit_ir(source: Path, outdir: Path, profile: Path | None) -> None:
    # Imported here so that `--version` and `--help` don't pay for loading PyMuPDF.
    from offprint.adapters.pdf import LayoutError, NoProfileMatch, UnreadablePdfError, emit_ir
    from offprint.profiles import ProfileError, load_profile_file

    if not source.is_file():
        typer.echo(f"offprint convert: no such file: {source}", err=True)
        raise typer.Exit(code=1)
    try:
        selected_profile = load_profile_file(profile) if profile is not None else None
        target = emit_ir(source, outdir, profile=selected_profile)
    except (LayoutError, NoProfileMatch, ProfileError, UnreadablePdfError) as error:
        typer.echo(f"offprint convert: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(target)


def _write_epub(
    source: str,
    outdir: Path,
    cover: bool,
    allow_review: bool,
    profile: Path | None,
    delivery: "_Delivery | None",
) -> None:
    # Imported here so that `--version` and `--help` don't pay for PyMuPDF and Playwright.
    from offprint.pipeline import ConvertError, convert_to_epub
    from offprint.qa import summary

    try:
        result = convert_to_epub(source, outdir, cover=cover, profile=profile)
    except ConvertError as error:
        typer.echo(f"offprint convert: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(result.path)
    typer.echo(summary(result.report, result.report_path), err=True)
    verdict = result.report.verdict
    if delivery is not None:
        _deliver("convert", result.path, verdict, delivery, allow_review=allow_review)
    elif verdict == "review" and not allow_review:
        raise typer.Exit(code=_REVIEW_EXIT_CODE)


@dataclass(frozen=True, slots=True)
class _Delivery:
    force: bool
    dry_run: bool


def _deliver(
    command: str, epub: Path, verdict: str | None, delivery: _Delivery, *, allow_review: bool
) -> None:
    from offprint.delivery import DeliveryError, VerdictBlocked
    from offprint.pipeline import send_book

    try:
        done = send_book(epub, verdict=verdict, force=delivery.force, dry_run=delivery.dry_run)
    except VerdictBlocked as error:
        typer.echo(f"offprint {command}: {error}", err=True)
        if not allow_review:
            raise typer.Exit(code=_REVIEW_EXIT_CODE) from error
        return
    except DeliveryError as error:
        typer.echo(f"offprint {command}: {error}", err=True)
        raise typer.Exit(code=1) from error
    shrunk = f", images downscaled to {done.shrunk_to} px" if done.shrunk_to else ""
    size = f"{done.message_bytes / 1e6:.1f} MB{shrunk}"
    if done.eml is not None:
        typer.echo(f"offprint {command}: dry run, wrote {done.eml} ({size})", err=True)
    else:
        typer.echo(f"offprint {command}: sent {epub.name} to {done.to} ({size})", err=True)


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
    profile: Annotated[
        Path | None,
        typer.Option(
            "--profile", metavar="PATH", help="Use this publisher profile YAML for a PDF."
        ),
    ] = None,
    no_cover: Annotated[bool, typer.Option("--no-cover", help="Don't generate a cover.")] = False,
    allow_review: Annotated[
        bool, typer.Option("--allow-review", help="Exit 0 even if the QA verdict is review.")
    ] = False,
    send_to_kindle: Annotated[
        bool,
        typer.Option(
            "--send", help="Email the book to your Kindle if it passed QA (see docs/delivery.md)."
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="With --send: send a book in review, or one already sent."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="With --send: write the .eml instead of sending.")
    ] = False,
) -> None:
    """Convert a paper into an EPUB and check it. Uses the network only with --send.

    Exits 1 if no book could be made and 3 if the book needs review (see `<name>.qa.md`); a book
    in review isn't sent unless --force.
    """
    if (force or dry_run) and not send_to_kindle:
        raise typer.BadParameter("--force and --dry-run only make sense with --send")
    if emit_ir:
        if send_to_kindle:
            raise typer.BadParameter("--send needs an EPUB, and --emit-ir doesn't write one")
        _emit_ir(Path(source), outdir, profile)
        return
    delivery = _Delivery(force=force, dry_run=dry_run) if send_to_kindle else None
    _write_epub(
        source,
        outdir,
        cover=not no_cover,
        allow_review=allow_review,
        profile=profile,
        delivery=delivery,
    )


@app.command()
def send(
    epub: Annotated[Path, typer.Argument(metavar="EPUB", help="The EPUB to send.")],
    qa: Annotated[
        Path | None,
        typer.Option(
            "--qa", metavar="QA_JSON", help="The QA report [<stem>.qa.json next to EPUB]."
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Send a book in review, or one already sent.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Write the .eml next to the EPUB instead of sending.")
    ] = False,
) -> None:
    """Email an EPUB to your Kindle. Only a book that passed QA is sent, unless --force.

    Reads the verdict from the QA report next to the book; no report counts as not passed.
    Exits 1 if it couldn't be sent and 3 if the verdict blocked it.
    """
    from offprint.delivery import DeliveryError, read_verdict

    if not epub.is_file():
        typer.echo(f"offprint send: no such file: {epub}", err=True)
        raise typer.Exit(code=1)
    try:
        verdict = read_verdict(epub, qa)
    except DeliveryError as error:
        typer.echo(f"offprint send: {error}", err=True)
        raise typer.Exit(code=1) from error
    _deliver("send", epub, verdict, _Delivery(force=force, dry_run=dry_run), allow_review=False)


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
    for table in result.overflowing_tables:
        typer.echo(f"Warning: a table is wider than the page: {table}", err=True)


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
