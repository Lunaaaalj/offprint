"""Licence URLs, as the registries give them, mapped to SPDX ids."""

import re

_CC_URL = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)/(\d\.\d)", re.I)


def spdx_from_url(url: str) -> str | None:
    """`https://creativecommons.org/licenses/by/4.0/` becomes `CC-BY-4.0`. Pure.

    Only Creative Commons licences and CC0 map. Anything else, such as arXiv's non-exclusive
    distribution licence, is `None`: it doesn't let us redistribute the paper, so it isn't guessed.
    """
    match = _CC_URL.search(url)
    if match is None:
        return None
    family, code, version = match.groups()
    if family.lower() == "publicdomain":
        return f"CC0-{version}" if code.lower() == "zero" else None
    return f"CC-{code.upper()}-{version}"
