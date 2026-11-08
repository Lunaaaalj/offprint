"""English words, for deciding line-end hyphens when a paper's own words give no evidence."""

from functools import cache
from importlib.resources import files


@cache
def english_words() -> frozenset[str]:
    """The packaged word list: lowercase, letters only. See `scripts/build_wordlist.py`."""
    text = (files("offprint.cleanup") / "data" / "words-en.txt").read_text(encoding="utf-8")
    return frozenset(line for line in text.splitlines() if line and not line.startswith("#"))
