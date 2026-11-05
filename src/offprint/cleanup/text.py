"""Text steps: turn what a PDF's spans hold into the text the author wrote."""

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal

from offprint.cleanup.registry import step
from offprint.extraction import Span
from offprint.ir import Bold, Italic, Runs, Sup, Text

type KeepHyphen = Callable[[str, str], bool]
"""Given the words on each side of a line-end hyphen, says whether it's a real compound."""

type HyphenBreak = Literal["join", "keep", "space"]

type _Style = tuple[bool, bool, bool]  # superscript, bold, italic
type _Piece = tuple[_Style, str]

LIGATURES: Mapping[str, str] = MappingProxyType(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)

# PDFs built from TeX fonts place a spacing accent before its letter.
SPACING_MARKS: Mapping[str, str] = MappingProxyType(
    {
        "¸": "\N{COMBINING CEDILLA}",
        "´": "\N{COMBINING ACUTE ACCENT}",
        "¨": "\N{COMBINING DIAERESIS}",
        "˜": "\N{COMBINING TILDE}",
        "ˆ": "\N{COMBINING CIRCUMFLEX ACCENT}",
        "ˇ": "\N{COMBINING CARON}",
        "˘": "\N{COMBINING BREVE}",
        "˙": "\N{COMBINING DOT ABOVE}",
        "˝": "\N{COMBINING DOUBLE ACUTE ACCENT}",
        "˚": "\N{COMBINING RING ABOVE}",
        "¯": "\N{COMBINING MACRON}",
    }
)

# Everything XML 1.0 can't hold, plus DEL. Tab, newline and carriage return are legal.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]")
_WHITESPACE = re.compile(r"\s+")
_LETTER = r"[^\W\d_]"
_HYPHENS = "\\-\N{SOFT HYPHEN}\N{HYPHEN}"
_LAST_WORD = re.compile(rf"({_LETTER}[\w{_HYPHENS}]*)[{_HYPHENS}]$")
_FIRST_WORD = re.compile(rf"{_LETTER}+")
_WORD = re.compile(rf"{_LETTER}[\w{_HYPHENS}]*")


@dataclass(frozen=True, slots=True, kw_only=True)
class TextOptions:
    ligatures: Mapping[str, str] = field(default_factory=lambda: LIGATURES)
    spacing_marks: Mapping[str, str] = field(default_factory=lambda: SPACING_MARKS)
    keep_hyphen: KeepHyphen | None = None


@step("strip_control_characters", "text")
def strip_control_characters(text: str) -> str:
    """Drop characters that make XHTML invalid (a stray one once lost a whole chapter)."""
    return _CONTROL.sub("", text)


@step("expand_ligatures", "text")
def expand_ligatures(text: str, ligatures: Mapping[str, str] = LIGATURES) -> str:
    for ligature, letters in ligatures.items():
        text = text.replace(ligature, letters)
    return text


@step("fix_combining_marks", "text")
def fix_combining_marks(text: str, marks: Mapping[str, str] = SPACING_MARKS) -> str:
    """Compose a spacing accent with the letter after it, and any decomposed letters.

    `¸S` becomes `Ş`. An accent that doesn't form a real letter is left alone.
    """

    def compose(match: re.Match[str]) -> str:
        composed = unicodedata.normalize("NFC", match[2] + marks[match[1]])
        return composed if len(composed) == 1 else match[0]

    if marks:
        text = re.sub(f"([{re.escape(''.join(marks))}])({_LETTER})", compose, text)
    return unicodedata.normalize("NFC", text)


@step("collapse_whitespace", "text")
def collapse_whitespace(text: str) -> str:
    """Turn each run of whitespace into one space. Edges stay: a space can separate two spans."""
    return _WHITESPACE.sub(" ", text)


def clean_text(text: str, options: TextOptions | None = None) -> str:
    """Apply every character-level step, in the order they depend on each other."""
    options = options or TextOptions()
    text = strip_control_characters(text)
    text = expand_ligatures(text, options.ligatures)
    text = fix_combining_marks(text, options.spacing_marks)
    return collapse_whitespace(text)


def hyphen_break(left: str, right: str, keep_hyphen: KeepHyphen | None = None) -> HyphenBreak:
    """Decide how two pieces of text meet at a line break.

    `join` drops the hyphen and closes up, `keep` keeps it and closes up, and `space` means this
    isn't a hyphen break at all.
    """
    before = _LAST_WORD.search(left)
    after = _FIRST_WORD.match(right)
    if before is None or after is None or not right[0].islower():
        return "space"
    if keep_hyphen is not None and keep_hyphen(before[1], after[0]):
        return "keep"
    return "join"


@step("dehyphenate", "text")
def dehyphenate(left: str, right: str, keep_hyphen: KeepHyphen | None = None) -> str:
    """Join text across a line break, closing up a word only before a lowercase continuation."""
    match hyphen_break(left, right, keep_hyphen):
        case "join":
            return left[:-1] + right
        case "keep":
            return left + right
        case "space":
            return f"{left} {right}"


def vocabulary(texts: Iterable[str]) -> frozenset[str]:
    """Return the casefolded words of `texts`, with hyphenated compounds as one word."""
    return frozenset(word.casefold() for text in texts for word in _WORD.findall(text))


def keep_hyphen_from_vocabulary(words: Iterable[str]) -> KeepHyphen:
    """Build a `keep_hyphen` hook from words seen whole, such as the rest of the same paper.

    The closed-up form wins if it was seen. Otherwise a hyphen stays if the hyphenated form was
    seen or both sides are words. So `in-formation` closes up in a paper that has `information`,
    while `magnetization-prepared` survives.
    """
    known = frozenset(word.casefold() for word in words)

    def keep_hyphen(left: str, right: str) -> bool:
        left, right = left.casefold(), right.casefold()
        if left + right in known:
            return False
        return f"{left}-{right}" in known or (left in known and right in known)

    return keep_hyphen


@step("separate_words", "text")
def separate_words(spans: Sequence[Span], word_gap: float = 1.0) -> tuple[Span, ...]:
    """Add a space between spans of one line, in x order, that a visible gap separates.

    Two spans can hold different words with no space character between them, usually where a
    table column was folded into its neighbour.
    """
    separated: list[Span] = []
    for span in spans:
        previous = separated[-1] if separated else None
        spaced = previous is None or previous.text[-1:].isspace() or span.text[:1].isspace()
        if previous is not None and not spaced and span.bbox[0] - previous.bbox[2] > word_gap:
            separated[-1] = replace(previous, text=previous.text + " ")
        separated.append(span)
    return tuple(separated)


@step("spans_to_runs", "text")
def spans_to_runs(lines: Sequence[Sequence[Span]], options: TextOptions | None = None) -> Runs:
    """Turn lines of spans into IR runs: clean text, keep styling, dehyphenate between lines."""
    options = options or TextOptions()
    pieces: list[_Piece] = []
    for spans in lines:
        line = _styled_pieces(spans, options)
        if not line:
            continue
        if pieces:
            left = "".join(text for _, text in pieces)
            right = "".join(text for _, text in line)
            how = hyphen_break(left, right, options.keep_hyphen)
            style, text = pieces[-1]
            if how == "join":
                pieces[-1] = (style, text[:-1])
            elif how == "space":
                pieces[-1] = (style, text + " ")
        pieces += line
    return _to_runs(pieces)


def _styled_pieces(spans: Sequence[Span], options: TextOptions) -> list[_Piece]:
    pieces: list[_Piece] = []
    for span in spans:
        text = clean_text(span.text, options)
        if not text.strip():
            # Whitespace has no style of its own: it stays with the text before it.
            if text and pieces:
                pieces[-1] = (pieces[-1][0], pieces[-1][1] + " ")
        elif span.superscript:
            pieces.append(((True, False, False), text.strip()))
        else:
            pieces.append(((False, span.bold, span.italic), text))
    if pieces:
        pieces[0] = (pieces[0][0], pieces[0][1].lstrip())
        pieces[-1] = (pieces[-1][0], pieces[-1][1].rstrip())
    return [piece for piece in pieces if piece[1]]


def _to_runs(pieces: Sequence[_Piece]) -> Runs:
    merged: list[_Piece] = []
    for style, text in pieces:
        if merged and merged[-1][0] == style:
            merged[-1] = (style, merged[-1][1] + text)
        elif text:
            merged.append((style, text))
    return tuple(_styled(style, text) for style, text in merged if text)


def _styled(style: _Style, text: str) -> Text | Bold | Italic | Sup:
    superscript, bold, italic = style
    if superscript:
        return Sup((Text(text),))
    if bold and italic:
        return Bold((Italic((Text(text),)),))
    if bold:
        return Bold((Text(text),))
    if italic:
        return Italic((Text(text),))
    return Text(text)
