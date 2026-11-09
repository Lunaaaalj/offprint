"""Single-column templates, shared math fonts and optional metadata in the profile schema (#35)."""

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from offprint import profiles
from offprint.adapters.pdf.equations import is_display_equation, math_font_share
from offprint.adapters.pdf.figures import figure_region
from offprint.adapters.pdf.layout import column_of, column_range, reading_order
from offprint.adapters.pdf.metadata import (
    BylineBlock,
    FrontMatter,
    build_meta,
    parse_keywords,
    parse_license,
    read_authors,
)
from offprint.adapters.pdf.tables import trim_detections
from offprint.extraction import ExtractedTable, Line, Span, TableCell, TextBlock
from offprint.ir import BBox
from offprint.profiles import ProfileError, load_profile
from offprint.profiles.schema import Metadata, build_profile

FRONTIERS = load_profile("frontiers")
FRONTIERS_YAML = Path(profiles.__file__).parent / "frontiers.yaml"
ONE_COLUMN = replace(
    FRONTIERS.page, split_x=None, full_width_margin=None, left=None, right=None, full=(108.0, 506.0)
)
SINGLE = replace(FRONTIERS, page=ONE_COLUMN)


@pytest.fixture
def data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(FRONTIERS_YAML.read_text(encoding="utf-8")))


def block(parts: list[tuple[str, str]], box: BBox, size: float = 10.0) -> TextBlock:
    """A one-line block made of (text, font) spans."""
    spans = tuple(Span(text=t, bbox=box, page=1, font=f, size=size) for t, f in parts)
    return TextBlock(lines=(Line(spans=spans, bbox=box),), bbox=box, page=1)


# The layout


def test_a_single_column_layout_has_no_gutter() -> None:
    assert ONE_COLUMN.single_column
    assert not FRONTIERS.page.single_column


def test_every_box_in_a_single_column_is_full_width() -> None:
    assert column_of((108, 0, 200, 10), ONE_COLUMN) == "full"
    assert column_of((400, 0, 506, 10), ONE_COLUMN) == "full"
    assert column_of((108, 0, 506, 10), ONE_COLUMN) == "full"


def test_every_column_has_the_text_area_in_a_single_column() -> None:
    assert column_range("left", ONE_COLUMN) == (108.0, 506.0)
    assert column_range("full", ONE_COLUMN) == (108.0, 506.0)


@dataclass
class Item:
    name: str
    column: str
    top: float
    bottom: float


def test_a_single_column_page_reads_top_down() -> None:
    items = [Item("c", "full", 300, 310), Item("a", "full", 100, 110), Item("b", "full", 200, 210)]

    assert [i.name for i in reading_order(items)] == ["a", "b", "c"]


def test_a_figure_in_a_single_column_uses_the_text_area_and_never_the_gutter() -> None:
    found = figure_region(
        (108, 400, 506, 410),
        blocks=[],
        captions=[],
        graphics=[],
        page_width=612.0,
        profile=SINGLE,
    )

    assert found.column == "full"
    assert (found.bbox[0], found.bbox[2]) == (108.0, 506.0)


def table_across_the_old_gutter() -> ExtractedTable:
    def box_cell(x0: float, x1: float) -> TableCell:
        return TableCell(spans=(), bbox=(x0, 0.0, x1, 20.0))

    return ExtractedTable(
        rows=((box_cell(108, 200), box_cell(200, 300), box_cell(305, 506)),),
        bbox=(108.0, 0.0, 506.0, 200.0),
        page=1,
    )


def test_a_single_column_has_no_swallowed_column_to_trim() -> None:
    # In two columns, text beside the table's right cell would mean the cell is a swallowed column.
    tables = [table_across_the_old_gutter()]
    text = block([("x", "MinionPro-Regular")], (305, 10, 506, 190))
    text = replace(text, lines=text.lines * 3)

    assert trim_detections(tables, [text], SINGLE) == tables


# The schema


def test_a_profile_may_leave_out_the_columns(data: dict[str, Any]) -> None:
    for key in ("split_x", "full_width_margin", "left", "right"):
        del data["page"][key]

    assert build_profile(data, "t").page.single_column


@pytest.mark.parametrize("key", ["split_x", "full_width_margin", "left", "right"])
def test_a_half_specified_two_column_layout_is_an_error(data: dict[str, Any], key: str) -> None:
    del data["page"][key]

    with pytest.raises(ProfileError, match=rf"t\.page: .*missing \['{key}'\]"):
        build_profile(data, "t")


@pytest.mark.parametrize("key", ["centred_marker", "corresponding_marker"])
def test_an_empty_marker_is_an_error(data: dict[str, Any], key: str) -> None:
    section = "equations" if key == "centred_marker" else "metadata"
    data[section][key] = ""

    with pytest.raises(ProfileError, match=rf"t\.{section}\.{key}: can't be empty"):
        build_profile(data, "t")


def test_a_profile_may_leave_out_the_metadata(data: dict[str, Any]) -> None:
    del data["metadata"]

    assert build_profile(data, "t").metadata == Metadata()


# Display math with shared fonts

CM = ["CMMI", "CMSY"]
SHARED = replace(
    SINGLE,
    equations=replace(
        SINGLE.equations, math_fonts=tuple(CM), math_font_share=0.6, centred_marker=None
    ),
)


def test_the_share_counts_characters_in_math_fonts() -> None:
    line = block([("ab", "NimbusRomNo9L-Regu"), ("cdef", "CMMI10")], (108, 100, 300, 110))

    assert math_font_share(line, CM) == pytest.approx(4 / 6)


def test_the_share_of_an_empty_block_is_zero() -> None:
    assert math_font_share(block([(" ", "CMMI10")], (0, 0, 1, 1)), CM) == 0.0


def test_a_body_line_with_a_few_symbols_is_not_display_math() -> None:
    line = block(
        [("the scores of size ", "NimbusRomNo9L-Regu"), ("d", "CMMI10"), (" are scaled", "Nimbus")],
        (108, 100, 506, 110),
    )

    assert not is_display_equation(line, "full", SHARED)


def test_a_block_set_mostly_in_math_fonts_is_display_math() -> None:
    line = block([("√", "CMSY10"), ("d", "CMMI10"), ("k", "CMMI7")], (250, 100, 300, 110))

    assert is_display_equation(line, "full", SHARED)


def test_a_math_font_alone_still_counts_when_no_share_is_set() -> None:
    line = block([("long body text here", "Nimbus"), ("d", "CMMI10")], (108, 100, 506, 110))

    assert is_display_equation(
        line, "full", replace(SHARED, equations=replace(SHARED.equations, math_font_share=0.0))
    )


def test_a_centred_block_without_a_marker_is_not_display_math() -> None:
    # An empty marker made every short indented block an equation (#43).
    line = block([("Attention", "Nimbus")], (250, 100, 350, 110))

    assert not is_display_equation(line, "full", SHARED)


# Optional metadata


def test_a_template_with_no_citation_gives_no_bibliographic_fields() -> None:
    meta = build_meta(FrontMatter(title="T", citation="Vol 3 (2017)"), {}, SINGLE_NO_METADATA)

    assert (meta.title, meta.year, meta.volume, meta.journal) == ("T", None, None, None)


SINGLE_NO_METADATA = replace(SINGLE, metadata=Metadata())


def test_no_license_rules_give_no_license() -> None:
    assert parse_license("(c) 2017 someone, CC BY 4.0", SINGLE_NO_METADATA) is None


def test_no_keyword_rules_give_no_keywords() -> None:
    assert parse_keywords("Keywords: a, b", SINGLE_NO_METADATA) == ()


def test_with_no_separator_each_author_block_is_one_person() -> None:
    byline = [
        BylineBlock(names="Ashish Vaswani and Noam Shazeer", affiliation="", bbox=(0, 0, 9, 9))
    ]

    authors = read_authors(byline, SINGLE_NO_METADATA)

    assert [a.name for a in authors] == ["Ashish Vaswani and Noam Shazeer"]
    assert not authors[0].corresponding
