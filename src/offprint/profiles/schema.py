"""The shape of a publisher profile, and the strict loader that checks a YAML file against it.

A profile holds every value specific to one journal template. Coordinates are in points, with the
origin at the top left of the page. Unknown keys are errors, so a typo can't silently do nothing.
"""

import dataclasses
import re
import types
from dataclasses import dataclass
from typing import Any, Literal, NewType, Union, get_args, get_origin, get_type_hints

type Range = tuple[float, float]
type Side = Literal["above", "below"]
type Pages = Literal["all", "first", "later"]
type Context = Literal["page", "caption", "table"]
type Role = Literal[
    "title",
    "h1",
    "h2",
    "h3",
    "authors",
    "affiliation",
    "abstract",
    "keywords",
    "body",
    "small",
    "caption",
    "table_header",
    "table_body",
    "ignore",
]

Regex = NewType("Regex", str)


class ProfileError(ValueError):
    """A profile is malformed. The message names the file and the key."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Match:
    """How to recognise the template. Every criterion listed must hold for a profile to match."""

    producer: Regex | None = None
    creator: Regex | None = None
    fonts: tuple[str, ...] = ()
    """Font name prefixes that must all be in the PDF."""
    text: tuple[Regex, ...] = ()
    """Patterns that must all appear in the text of the first page."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Sidebar:
    page: int
    x_max: float
    """Blocks that end left of this are in the sidebar."""
    keep: Regex
    """Sidebar blocks that match are kept as front matter. The rest are dropped."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PageLayout:
    header_y: float
    """Text that ends above this is the running header."""
    footer_y: float
    """Text that starts below this is the running footer."""
    split_x: float
    """The middle of the gutter between the two columns."""
    full_width_margin: float
    """A box reaching this far past `split_x` on both sides is full width."""
    left: Range
    right: Range
    full: Range
    sidebar: Sidebar | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FontStyles:
    """Substrings of a font name that mean a style."""

    bold: tuple[str, ...]
    italic: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleRule:
    """One line of the font table. The first rule that matches a block decides its role."""

    role: Role
    context: Context = "page"
    fonts: tuple[str, ...] = ()
    """Font name prefixes. Empty means any font."""
    size: Range | None = None
    """Lower bound included, upper bound excluded."""
    pages: Pages = "all"
    text: Regex | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Headings:
    number: Regex
    """Splits a heading into groups `number` and `text`."""
    levels: tuple[str, ...]
    """Heading roles, top level first. The role at index i becomes IR level i + 1."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Captions:
    figure: Regex
    """Matches a figure caption, with groups `number` and `text`."""
    table: Regex
    """Matches a table caption, with groups `number` and `text`."""
    figure_side: Literal["below"]
    table_side: Side
    continuation: Regex
    """Matches the text of a table caption that continues an earlier table."""
    fonts: tuple[str, ...]
    """Only spans in these fonts belong to a caption's text."""
    touch_gap: float
    line_tolerance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Figures:
    zoom: float
    bounding_fonts: tuple[str, ...]
    """Blocks in these fonts bound a figure from above. Chart labels are in other fonts."""
    min_graphic_size: float
    """Drawn shapes narrower or shorter than this don't count towards a figure."""
    crop_margin: float
    """Space kept around the drawn shapes."""
    full_width_overlap: float
    """A shape reaching this far past `split_x` on both sides makes a figure full width."""
    edge_tolerance: float
    """Slack when comparing a shape's edges with the region's edges."""
    block_gap: float
    """A bounding block must end this far above the caption."""
    caption_reach: float
    """A caption further right of this one's left edge doesn't bound it."""
    fallback_top_margin: float
    """With no shapes, the crop starts this far below the bound."""
    fallback_bottom_margin: float
    """With no shapes, the crop ends this far above the caption."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Tables:
    text_fonts: tuple[str, ...]
    """Running text in these fonts shows that a detected table swallowed a column."""
    text_min_size: float
    text_min_lines: int
    swallow_overlap: float
    keep_margin: float
    line_tolerance: float
    word_gap: float
    caption_tolerance: float
    reference_headers: tuple[str, ...]
    year_pattern: Regex


@dataclass(frozen=True, slots=True, kw_only=True)
class Equations:
    zoom: float
    grayscale: bool
    math_fonts: tuple[str, ...]
    number: Regex
    """A span that is only an equation number, with group `number`."""
    trailing_number: Regex
    """A line ending in an equation number, with group `number`."""
    right_edge_tolerance: float
    """A trailing number counts when its line ends this close to the column's right edge."""
    max_numbered_lines: int
    max_centred_lines: int
    centred_indent: float
    """A centred block starts this far inside the column."""
    centred_min_size: float
    centred_marker: str
    """A centred block must contain this to be an equation."""
    merge_gap: float
    """Pieces closer than this vertically belong to one equation."""
    crop_margin: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ScriptRules:
    size_ratio: float
    """A span smaller than this share of its line's main size may be a sub- or superscript."""
    offset: float
    """How far, in points, its vertical centre must sit above or below the main text's."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TextRules:
    paragraph_end: Regex
    """A paragraph whose text matches this is finished."""
    loose_join_roles: tuple[Literal["body", "abstract", "small", "meta"], ...]
    """In these roles an unfinished paragraph absorbs the next even if it starts uppercase."""
    bullet: Regex
    """Matches the start of a list item."""
    word_gap: float
    line_end_hyphens: Literal["keep", "vocabulary"]
    """`keep` is for templates that never break words, where a hyphen at the end of a line is part
    of a compound. `vocabulary` closes up a word unless the paper's own words say otherwise."""
    scripts: ScriptRules | None = None
    """Where to find subscripts and superscripts from the geometry of the spans. Without it, only
    the PDF's own superscript flag is used."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LicenseRule:
    pattern: Regex
    spdx: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Metadata:
    citation: Regex
    """Searched in the citation text, with optional groups `year`, `journal`, `volume`,
    `article_id` and `doi`."""
    citation_block: Regex
    """Matches the front-matter block that holds the citation."""
    copyright_block: Regex
    """Matches the front-matter block that holds the copyright notice."""
    holder: Regex
    """Finds the copyright holder in that block, as group `holder`."""
    licenses: tuple[LicenseRule, ...]
    author_separator: Regex
    corresponding_marker: str
    keyword_prefix: Regex
    keyword_separator: Regex


@dataclass(frozen=True, slots=True, kw_only=True)
class References:
    heading: Regex
    """The heading of the reference list. Paragraphs under it are references."""
    doi: Regex
    """Finds a reference's DOI, as group `doi`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    name: str
    match: Match
    page: PageLayout
    fonts: FontStyles
    roles: tuple[RoleRule, ...]
    headings: Headings
    captions: Captions
    figures: Figures
    tables: Tables
    equations: Equations
    text: TextRules
    metadata: Metadata
    references: References


def build_profile(data: Any, source: str) -> Profile:
    """Check parsed YAML against `Profile`, raising `ProfileError` for anything that doesn't fit."""
    profile = _dataclass(Profile, data, source)
    for key, pattern in (
        ("headings.number", profile.headings.number),
        ("captions.figure", profile.captions.figure),
        ("captions.table", profile.captions.table),
    ):
        missing = {"number", "text"} - set(re.compile(pattern).groupindex)
        if missing:
            raise ProfileError(f"{source}.{key}: needs the groups {sorted(missing)}")
    return profile


def _dataclass(cls: Any, value: Any, path: str) -> Any:
    if not isinstance(value, dict):
        raise ProfileError(f"{path}: expected a mapping, got {type(value).__name__}")
    fields = {field.name: field for field in dataclasses.fields(cls)}
    unknown = set(value) - set(fields)
    if unknown:
        raise ProfileError(f"{path}: unknown keys {sorted(map(str, unknown))}")
    required = {
        name
        for name, field in fields.items()
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    }
    missing = required - set(value)
    if missing:
        raise ProfileError(f"{path}: missing keys {sorted(missing)}")
    hints = get_type_hints(cls)
    return cls(
        **{name: _convert(hints[name], item, f"{path}.{name}") for name, item in value.items()}
    )


def _convert(kind: Any, value: Any, path: str) -> Any:
    kind = getattr(kind, "__value__", kind)
    origin = get_origin(kind)
    if dataclasses.is_dataclass(kind):
        return _dataclass(kind, value, path)
    if kind is Regex:
        return _regex(value, path)
    if origin is Literal:
        if value not in get_args(kind):
            raise ProfileError(f"{path}: {value!r} is not one of {get_args(kind)}")
        return value
    if origin in (Union, types.UnionType):
        return _optional(kind, value, path)
    if origin is tuple:
        return _tuple(kind, value, path)
    if kind is float and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if kind in (str, int, bool) and type(value) is kind:
        return value
    raise ProfileError(f"{path}: expected {getattr(kind, '__name__', kind)}, got {value!r}")


def _regex(value: Any, path: str) -> Regex:
    if not isinstance(value, str):
        raise ProfileError(f"{path}: expected a regex, got {value!r}")
    try:
        re.compile(value)
    except re.error as error:
        raise ProfileError(f"{path}: invalid regex {value!r}: {error}") from error
    return Regex(value)


def _optional(kind: Any, value: Any, path: str) -> Any:
    options = [option for option in get_args(kind) if option is not type(None)]
    return None if value is None else _convert(options[0], value, path)


def _tuple(kind: Any, value: Any, path: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ProfileError(f"{path}: expected a list, got {value!r}")
    items = get_args(kind)
    if len(items) == 2 and items[1] is Ellipsis:
        return tuple(_convert(items[0], item, f"{path}[{i}]") for i, item in enumerate(value))
    if len(items) != len(value):
        raise ProfileError(f"{path}: expected {len(items)} items, got {len(value)}")
    pairs = enumerate(zip(items, value, strict=True))
    return tuple(_convert(kind, item, f"{path}[{i}]") for i, (kind, item) in pairs)
