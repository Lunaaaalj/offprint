"""What the PDF adapter reads for the QA gate, apart from the IR."""

from pathlib import Path

from offprint.adapters.pdf import read_evidence
from offprint.adapters.pdf.evidence import collect_evidence, source_text
from offprint.adapters.pdf.extract import PageData
from offprint.extraction import Line, SourceEquation, Span, TextBlock
from offprint.ir import BBox
from offprint.profiles import load_profile

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"
PROFILE = load_profile("frontiers")
BOX: BBox = (49.0, 100.0, 291.0, 110.0)


def block(
    *lines: str, box: BBox = BOX, page: int = 2, font: str = "MinionPro-Regular"
) -> TextBlock:
    built = tuple(
        Line(
            spans=(Span(text=line, bbox=box, page=page, font=font, size=9.0),),
            bbox=box,
        )
        for line in lines
    )
    return TextBlock(lines=built, bbox=box, page=page)


def page(*blocks: TextBlock, number: int = 2) -> PageData:
    return PageData(
        number=number,
        width=595.0,
        height=842.0,
        blocks=blocks,
        tables=(),
        graphics=(),
        figure_alts=(),
    )


def texts(*pages: PageData) -> list[str]:
    return [item.text for item in collect_evidence(pages, PROFILE).texts]


def test_reading_text_keeps_its_page_and_box() -> None:
    found = collect_evidence([page(block("Some body text."))], PROFILE)

    assert found.pages == 1
    assert found.texts[0].text == "Some body text."
    assert (found.texts[0].page, found.texts[0].bbox) == (2, BOX)


def test_running_heads_are_not_reading_text() -> None:
    header = block("frontiersin.org", box=(49.0, 20.0, 291.0, 30.0))
    footer = block("Page 2", box=(49.0, 800.0, 291.0, 810.0))

    assert texts(page(header, footer)) == []


def test_text_the_profile_ignores_is_not_reading_text() -> None:
    assert texts(page(block("Accuracy", font="Calibri"))) == []


def test_only_the_kept_part_of_the_sidebar_is_reading_text() -> None:
    sidebar = (49.0, 100.0, 150.0, 110.0)
    kept = block("CITATION Nibila Y", box=sidebar, page=1)
    dropped = block("EDITED BY Someone", box=sidebar, page=1)

    assert texts(page(kept, dropped, number=1)) == ["CITATION Nibila Y"]


def test_lines_are_joined_the_way_the_profile_treats_hyphens() -> None:
    text = source_text(block("a well-", "known result"), PROFILE, lambda left, right: True)

    assert text == "a well-known result"
    joined = source_text(block("classi-", "fication"), PROFILE, lambda left, right: False)
    assert joined == "classification"


def test_a_continued_caption_is_marked() -> None:
    box = (49.0, 100.0, 291.0, 110.0)
    first = block("TABLE 3 Results.", box=box, font="MuseoSans-700")
    later = block("TABLE 3 (Continued)", box=box, font="MuseoSans-700", page=3)

    found = collect_evidence([page(first), page(later, number=3)], PROFILE)

    assert [(c.kind, c.number, c.continued) for c in found.captions] == [
        ("table", "3", False),
        ("table", "3", True),
    ]


def test_an_equation_number_at_the_columns_edge_is_found() -> None:
    box = (100.0, 100.0, 290.0, 110.0)

    found = collect_evidence([page(block("x = y + z (7)", box=box))], PROFILE)

    assert found.equations == (SourceEquation(number="7", page=2, bbox=box),)


def test_the_fixture_shows_what_its_source_md_says() -> None:
    found = read_evidence(PDF)

    captions = [caption for caption in found.captions if not caption.continued]
    assert found.pages == 35
    assert sum(1 for caption in captions if caption.kind == "figure") == 24
    assert sum(1 for caption in captions if caption.kind == "table") == 20
    assert [item.number for item in found.equations] == [str(n) for n in range(1, 19)]
