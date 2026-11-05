"""JATS adapter: map an article's XML to the IR (#10).

JATS labels what a PDF hides, so this is a mapping rather than a reconstruction. `convert_jats`
never uses the network: `resolve` puts the article's graphics beside the XML first.
"""

from dataclasses import dataclass
from pathlib import Path

from offprint.adapters.jats.blocks import BlockMapper, LoadGraphic
from offprint.adapters.jats.evidence import collect_evidence, read_evidence
from offprint.adapters.jats.front import read_meta
from offprint.adapters.jats.graphics import (
    GRAPHICS_DIR,
    GraphicRefs,
    Unreadable,
    graphic_name,
    graphic_refs,
    load_graphic,
    pmc_version,
)
from offprint.adapters.jats.xml import Element, JatsError, parse_article
from offprint.ir import Document, Problem


class MissingGraphicsError(JatsError):
    """The article needs image files that aren't on disk."""

    def __init__(self, missing: tuple[str, ...], directories: tuple[Path, ...]) -> None:
        looked = " and ".join(str(directory) for directory in directories)
        super().__init__(
            f"jats.graphic_missing: {len(missing)} graphic(s) aren't available: "
            f"{', '.join(missing)}. Looked in {looked}. "
            "For a DOI, run `offprint resolve --refresh`."
        )
        self.missing = missing


@dataclass(frozen=True, slots=True)
class JatsResult:
    document: Document
    problems: tuple[Problem, ...]


def convert_jats(path: Path) -> JatsResult:
    """Convert a JATS file, with its graphics in `graphics/` or beside it.

    Raises `JatsError`, or `MissingGraphicsError` if a graphic isn't there: a figure the source has
    must not vanish from the book.
    """
    try:
        data = path.read_bytes()
    except OSError as error:
        raise JatsError(f"can't read {path}: {error}") from error
    directories = (path.parent / GRAPHICS_DIR, path.parent)
    result, missing = map_article(parse_article(data), lambda name: load_graphic(name, directories))
    if missing:
        raise MissingGraphicsError(missing, directories)
    return result


def map_article(article: Element, load: LoadGraphic) -> tuple[JatsResult, tuple[str, ...]]:
    """Map a parsed article, and say which graphics `load` couldn't supply. Does no I/O itself."""
    problems: list[Problem] = []
    meta = read_meta(article, problems)
    mapper = BlockMapper(article, load, problems=problems)
    mapper.run()
    document = Document(
        meta=meta,
        blocks=tuple(mapper.blocks),
        assets=mapper.assets,
        provenance=mapper.provenance,
    )
    return JatsResult(document, tuple(mapper.problems)), tuple(mapper.missing)


__all__ = [
    "GRAPHICS_DIR",
    "GraphicRefs",
    "JatsError",
    "JatsResult",
    "MissingGraphicsError",
    "Unreadable",
    "collect_evidence",
    "convert_jats",
    "graphic_name",
    "graphic_refs",
    "map_article",
    "parse_article",
    "pmc_version",
    "read_evidence",
]
