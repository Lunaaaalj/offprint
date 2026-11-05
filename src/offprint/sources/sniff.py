"""Check that downloaded bytes are what the candidate promised. Pure.

Servers answer with login pages and bot challenges under a 200 status, so a download only counts
once its content has been recognised.
"""

import re
import zlib
from typing import Literal

_TAR_MAGIC_OFFSET = 257
_TAR_BLOCK = 512
# The XML prologue: declaration, processing instructions, comments and the doctype.
_PROLOGUE = re.compile(rb"\s*(?:(?:<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>)\s*)*", re.DOTALL)
_JATS_ROOT = re.compile(rb"<(?:article|pmc-articleset)[\s>]")
_BODY = re.compile(rb"<body[\s>/]")
_IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF8", b"II*\x00", b"MM\x00*")

type EprintKind = Literal["tar.gz", "tar", "tex.gz", "pdf", "unknown"]


def classify_eprint(body: bytes) -> EprintKind:
    """Say what arXiv's `/e-print/` served: not every paper has TeX source.

    Decompresses only one tar block, so a gzip bomb can't fill the memory.
    """
    if body.startswith(b"%PDF"):
        return "pdf"
    if _is_tar(body):
        return "tar"
    if body.startswith(b"\x1f\x8b"):
        try:
            inner = zlib.decompressobj(wbits=31).decompress(body, _TAR_BLOCK)
        except zlib.error:
            return "unknown"
        return "tar.gz" if _is_tar(inner) else "tex.gz"
    return "unknown"


def is_jats(body: bytes) -> bool:
    """True for a JATS article with full text, bare or in PMC's `pmc-articleset` wrapper.

    An `<article>` with no `<body>` is the front matter a publisher allows when it withholds the
    full text, which is no use to an adapter.
    """
    prologue = _PROLOGUE.match(body)
    start = prologue.end() if prologue else 0
    return _JATS_ROOT.match(body, start) is not None and _BODY.search(body) is not None


def is_pdf(body: bytes) -> bool:
    return body.startswith(b"%PDF-")


def is_image(body: bytes) -> bool:
    """True for the formats publishers use for figures. A 200 can still be a login page."""
    return body.startswith(_IMAGE_SIGNATURES)


def _is_tar(data: bytes) -> bool:
    return data[_TAR_MAGIC_OFFSET : _TAR_MAGIC_OFFSET + 5] == b"ustar"
