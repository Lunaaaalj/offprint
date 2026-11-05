"""The last line of defence for XHTML: one stray control character can lose a whole chapter."""

import re

_PLANE_END_NONCHARACTERS = "".join(
    f"{chr(plane * 0x10000 + 0xFFFE)}{chr(plane * 0x10000 + 0xFFFF)}" for plane in range(17)
)
_FORBIDDEN = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"  # C0 controls, which XML 1.0 forbids
    "\x7f-\x9f"  # DEL and C1 controls: allowed by XML, forbidden in EPUB's HTML
    "\ud800-\udfff"  # lone surrogates, which can't even be encoded as UTF-8
    "﷐-﷯"  # non-characters
    f"{_PLANE_END_NONCHARACTERS}"
    "]"
)


def strip_invalid_xml(text: str) -> tuple[str, list[str]]:
    """Return `text` without the characters XHTML can't hold, and the code points removed."""
    removed = [f"U+{ord(char):04X}" for char in _FORBIDDEN.findall(text)]
    return (_FORBIDDEN.sub("", text) if removed else text), removed
