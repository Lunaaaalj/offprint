"""The words on the cover: kicker, authors and footer."""

import pytest

from offprint.cover.text import (
    format_authors,
    format_citation,
    format_imprint,
    format_license,
    split_kicker,
)
from offprint.ir import Author, License, Meta


def authors(*names: str) -> tuple[Author, ...]:
    return tuple(Author(name=name) for name in names)


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ((), ""),
        (("A",), "A"),
        (("A", "B"), "A & B"),
        (("A", "B", "C", "D"), "A, B, C & D"),
        (("A", "B", "C", "D", "E"), "A, B, … & E"),
        (tuple("ABCDEFGHIJKZ"), "A, B, … & Z"),
    ],
)
def test_authors_truncate_past_four(names: tuple[str, ...], expected: str) -> None:
    assert format_authors(authors(*names)) == expected


def test_the_fixture_title_gives_its_article_type_to_the_kicker() -> None:
    title = "Artificial intelligence techniques using neuroimaging data: a review"

    assert split_kicker(title) == (
        "Artificial intelligence techniques using neuroimaging data",
        "a review",
    )


@pytest.mark.parametrize(
    ("title", "kicker"),
    [
        ("Foo: a systematic review", "a systematic review"),
        ("Foo: A Survey.", "A Survey"),
        ("Foo — a systematic review and meta-analysis", "a systematic review and meta-analysis"),
    ],
)
def test_article_type_suffixes(title: str, kicker: str) -> None:
    assert split_kicker(title) == ("Foo", kicker)


@pytest.mark.parametrize(
    "title",
    [
        "A review of foo",
        "Foo: bar and baz",
        "Reviewing: the case of foo in the wild of many things",
    ],
)
def test_a_title_without_a_type_suffix_is_untouched(title: str) -> None:
    assert split_kicker(title) == (title, None)


def test_titles_lose_extraction_whitespace() -> None:
    assert split_kicker("Two\n  lines") == ("Two lines", None)


def test_the_footer_matches_the_example() -> None:
    meta = Meta(
        title="T",
        journal="Front. Artif. Intell.",
        volume="9",
        article_id="1748985",
        year=2026,
        license=License(spdx="CC-BY-4.0"),
    )

    assert format_citation(meta) == "Front. Artif. Intell. 9:1748985"
    assert format_imprint(meta) == "2026 · CC BY 4.0"


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        (Meta(title="T", journal="J"), "J"),
        (Meta(title="T", journal="J", volume="9"), "J 9"),
        (Meta(title="T", arxiv_id="2401.00001"), "arXiv:2401.00001"),
        (Meta(title="T", doi="10.1/x"), "doi:10.1/x"),
        (Meta(title="T"), ""),
    ],
)
def test_the_citation_uses_the_best_identifier_held(meta: Meta, expected: str) -> None:
    assert format_citation(meta) == expected


@pytest.mark.parametrize(
    ("spdx", "expected"),
    [("CC-BY-NC-ND-4.0", "CC BY NC ND 4.0"), ("CC0-1.0", "CC0 1.0"), ("MIT", "MIT")],
)
def test_licenses_read_the_way_readers_know_them(spdx: str, expected: str) -> None:
    assert format_license(spdx) == expected


def test_the_imprint_drops_what_it_lacks() -> None:
    assert format_imprint(Meta(title="T", year=2020)) == "2020"
    assert format_imprint(Meta(title="T")) == ""
