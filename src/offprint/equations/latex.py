"""Reduce what adapters hand over to a bare formula. Pure.

PubMed Central's `<tex-math>` often holds a whole document (`\\documentclass{minimal}` ...
`\\begin{document}$$...$$\\end{document}`), and LaTeX sources keep their math delimiters.
"""

import re

_DOCUMENT = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.DOTALL)
_TAG = re.compile(r"\\tag\*?\{([^{}]*)\}")
_DELIMITERS = (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$"))


def split_tags(latex: str) -> tuple[str, str | None]:
    """Take `\\tag{...}` out of a formula and return it apart, joined if there are several.

    The IR keeps numbers apart from the formula, so they stay readable as text. MathJax would also
    set a tag against the page's right edge, which an image hasn't got.
    """
    tags = [tag.strip() for tag in _TAG.findall(latex)]
    return _TAG.sub("", latex), ", ".join(tags) or None


def clean_latex(latex: str) -> str:
    """Return the formula inside any document wrapper and math delimiters."""
    text = latex.strip()
    if document := _DOCUMENT.search(text):
        text = document[1].strip()
    for start, end in _DELIMITERS:
        inner = text[len(start) : -len(end)]
        if len(text) > len(start) + len(end) and text.startswith(start) and text.endswith(end):
            # "$a$ and $b$" starts and ends with a delimiter too, and isn't one formula.
            if end not in inner:
                return inner.strip()
    return text
