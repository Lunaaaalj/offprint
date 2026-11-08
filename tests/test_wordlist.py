"""The English word list and the script that builds it (issue #46)."""

import importlib.util
from pathlib import Path

import pytest

from offprint.cleanup.dictionary import english_words

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_wordlist.py"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_wordlist", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AFF = """\
SET UTF-8
PFX U Y 1
PFX U   0     un         .
SFX D Y 3
SFX D   0     d          e
SFX D   y     ied        [^aeiou]y
SFX D   0     ed         [^ey]
SFX S Y 3
SFX S   y     ies        [^aeiou]y
SFX S   0     es         [sxzh]
SFX S   0     s          [^sxzhy]
SFX M Y 1
SFX M   0     's         .
"""


def test_suffixes_apply_where_their_condition_holds(build) -> None:
    dic = "4\nalign/DSU\nrelate/DU\ncarry/DS\nbox/S\n"

    words = build.expand(dic, AFF)

    assert {"align", "aligned", "aligns"} <= words
    assert {"relate", "related"} <= words
    assert {"carry", "carried", "carries"} <= words
    assert "boxes" in words
    assert "relateed" not in words and "boxs" not in words


def test_a_prefix_crosses_with_the_suffixes_of_a_cross_product_flag(build) -> None:
    words = build.expand("2\nalign/DU\nrelate/U\n", AFF)

    assert {"unalign", "unaligned", "unrelate"} <= words


def test_only_letters_survive_and_case_is_folded(build) -> None:
    words = build.expand("3\nBerkeley\ncan't\n42nd/M\n", AFF)

    assert words == {"berkeley"}


def test_the_license_section_is_copied_up_to_the_build_date(build) -> None:
    readme = "intro\nCOPYRIGHT, SOURCES, and CREDITS:\n\nCopyright 2000 X\n\nBuild Date: today\n"

    assert build.license_notice(readme) == [
        "COPYRIGHT, SOURCES, and CREDITS:",
        "",
        "Copyright 2000 X",
    ]


def test_the_list_is_sorted_one_word_per_line_with_the_notice(build) -> None:
    text = build.render({"b", "a"}, ["COPYRIGHT, SOURCES, and CREDITS:", "Copyright 2000 X"])

    lines = text.splitlines()
    assert lines[-2:] == ["a", "b"]
    assert all(line.startswith("#") for line in lines[:-2])
    assert "# Copyright 2000 X" in lines


def test_the_pinned_checksums_look_like_sha256(build) -> None:
    assert set(build.PACKAGES) == {"en_US", "en_GB-ize"}
    assert all(len(digest) == 64 and int(digest, 16) >= 0 for digest in build.PACKAGES.values())


# The list that ships


def test_the_shipped_list_has_what_the_hyphen_rule_needs() -> None:
    words = english_words()

    assert {"sequence", "aligned", "multiplicative", "information", "attention"} <= words
    assert {"color", "colour"} <= words
    assert not words & {"sequencealigned", "convolu", "tional", "plicative"}


def test_the_shipped_list_is_lowercase_letters_only() -> None:
    assert all(word.isalpha() and word == word.casefold() for word in english_words())


def test_the_shipped_list_keeps_the_copyright_notice() -> None:
    text = (Path(__file__).parent.parent / "src/offprint/cleanup/data/words-en.txt").read_text()

    assert "Copyright 2000-2026 by Kevin Atkinson" in text
    assert "provided that the" in text and "above copyright notice appears in all copies" in text
