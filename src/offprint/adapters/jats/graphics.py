"""Which image files an article needs, and reading them from disk. No network here.

`resolve` downloads what `graphic_names` lists into a `graphics` directory beside the XML, and
`convert` reads them from there. `xlink:href` is untrusted, so it only ever becomes a file name
through `graphic_name`, and it is never fetched as a URL.
"""

import io
import re
from pathlib import Path
from typing import NamedTuple

from PIL import Image, UnidentifiedImageError

from offprint.adapters.jats.xml import XLINK_HREF, Element, JatsError, text_of
from offprint.ir import Asset

GRAPHICS_DIR = "graphics"
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")


class GraphicRefs(NamedTuple):
    """The files an article refers to. `rejected` holds hrefs that can't be file names."""

    names: tuple[str, ...]
    rejected: tuple[str, ...]


class Unreadable(JatsError):
    """A graphic's file exists but isn't an image."""


def graphic_name(href: str) -> str | None:
    """The file name for an `xlink:href`, or `None` if it isn't a plain file name."""
    return href if _SAFE_NAME.fullmatch(href) and ".." not in href else None


def graphic_refs(article: Element) -> GraphicRefs:
    """List the graphics in the body and back matter, in order, without repeats."""
    hrefs: dict[str, None] = {}
    for part in article.iter("body", "back", "floats-group"):
        for graphic in part.iter("graphic"):
            hrefs[graphic.get(XLINK_HREF, "")] = None
    names = tuple(href for href in hrefs if graphic_name(href))
    return GraphicRefs(names, tuple(href for href in hrefs if not graphic_name(href)))


def pmc_version(article: Element) -> str | None:
    """The versioned PMC id, such as `PMC123.1`, that names the article's open-access files."""
    versioned = text_of(article.find("front/article-meta/article-id[@pub-id-type='pmcid-ver']"))
    if versioned:
        return versioned
    for kind in ("pmcid", "pmc"):
        found = text_of(article.find(f"front/article-meta/article-id[@pub-id-type='{kind}']"))
        if found:
            return f"PMC{found.removeprefix('PMC')}.1"
    return None


def load_graphic(name: str, directories: tuple[Path, ...]) -> Asset | None:
    """Read a graphic: `None` if it's not in `directories`, `Unreadable` if it isn't an image."""
    for directory in directories:
        path = directory / name
        if path.is_file():
            return _asset(name, path.read_bytes())
    return None


def _asset(name: str, data: bytes) -> Asset:
    try:
        with Image.open(io.BytesIO(data)) as image:
            mime = Image.MIME.get(image.format or "", "application/octet-stream")
            return Asset(id=name, mime=mime, bytes=data, width=image.width, height=image.height)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise Unreadable(f"jats.graphic_unreadable: {name} isn't an image: {error}") from error
