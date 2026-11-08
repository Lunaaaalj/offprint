"""Profiles: the schema rejects mistakes, and matching names the closest profile on failure."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from offprint import profiles
from offprint.profiles import (
    DocumentFacts,
    NoProfileMatch,
    ProfileError,
    available_profiles,
    load_profile,
    load_profile_file,
    select_profile,
)
from offprint.profiles.schema import build_profile

FRONTIERS = Path(profiles.__file__).parent / "frontiers.yaml"
FRONTIERS_FACTS = DocumentFacts(
    fonts=frozenset({"MinionPro-Regular", "MuseoSans-500"}), text="Frontiers  01  frontiersin.org"
)


@pytest.fixture
def data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(FRONTIERS.read_text(encoding="utf-8")))


def test_the_frontiers_profile_loads() -> None:
    profile = load_profile("frontiers")

    assert profile.name == "frontiers"
    assert profile.page.split_x == 297.5
    assert profile.captions.table_side == "above"
    assert available_profiles() == ("frontiers",)


def test_a_profile_loads_from_a_file() -> None:
    assert load_profile_file(FRONTIERS) == load_profile("frontiers")


def test_an_unknown_profile_lists_the_available_ones() -> None:
    with pytest.raises(ProfileError, match="frontiers"):
        load_profile("nature")


def test_scripts_are_optional_and_read_from_the_profile(data: dict[str, Any]) -> None:
    data["text"].pop("scripts", None)
    assert build_profile(data, "t").text.scripts is None

    data["text"]["scripts"] = {"size_ratio": 0.88, "offset": 0.7}
    scripts = build_profile(data, "t").text.scripts
    assert (scripts.size_ratio, scripts.offset) == (0.88, 0.7)


def test_a_scripts_section_needs_both_thresholds(data: dict[str, Any]) -> None:
    data["text"]["scripts"] = {"size_ratio": 0.88}

    with pytest.raises(ProfileError, match=r"t\.text\.scripts: missing keys \['offset'\]"):
        build_profile(data, "t")


def test_a_reference_entry_marker_is_optional(data: dict[str, Any]) -> None:
    assert build_profile(data, "t").references.entry_start is None

    data["references"]["entry_start"] = r"^\[\d+\]"
    assert build_profile(data, "t").references.entry_start == r"^\[\d+\]"

    data["references"]["entry_start"] = "["
    with pytest.raises(ProfileError, match=r"t\.references\.entry_start: invalid regex"):
        build_profile(data, "t")


def test_a_typo_in_a_key_is_an_error(data: dict[str, Any]) -> None:
    data["page"]["split_xx"] = 1

    with pytest.raises(ProfileError, match=r"t\.page: unknown keys \['split_xx'\]"):
        build_profile(data, "t")


def test_a_missing_key_is_an_error(data: dict[str, Any]) -> None:
    del data["captions"]["table"]

    with pytest.raises(ProfileError, match=r"t\.captions: missing keys \['table'\]"):
        build_profile(data, "t")


def test_a_wrong_type_is_an_error(data: dict[str, Any]) -> None:
    data["page"]["split_x"] = "middle"

    with pytest.raises(ProfileError, match=r"t\.page\.split_x"):
        build_profile(data, "t")


def test_a_bad_regex_is_an_error(data: dict[str, Any]) -> None:
    data["captions"]["continuation"] = "("

    with pytest.raises(ProfileError, match=r"t\.captions\.continuation: invalid regex"):
        build_profile(data, "t")


def test_a_caption_regex_needs_its_groups(data: dict[str, Any]) -> None:
    data["captions"]["figure"] = "^FIGURE"

    with pytest.raises(ProfileError, match=r"t\.captions\.figure: needs the groups"):
        build_profile(data, "t")


def test_an_unknown_role_is_an_error(data: dict[str, Any]) -> None:
    data["roles"][0]["role"] = "sidebar"

    with pytest.raises(ProfileError, match=r"t\.roles\[0\]\.role"):
        build_profile(data, "t")


def test_a_range_needs_two_values(data: dict[str, Any]) -> None:
    data["page"]["left"] = [1, 2, 3]

    with pytest.raises(ProfileError, match=r"t\.page\.left: expected 2 items"):
        build_profile(data, "t")


def test_invalid_yaml_is_a_profile_error(tmp_path: Path) -> None:
    file = tmp_path / "bad.yaml"
    file.write_text("a: [", encoding="utf-8")

    with pytest.raises(ProfileError, match="bad.yaml: not valid YAML"):
        load_profile_file(file)


def test_a_matching_document_selects_the_profile() -> None:
    assert select_profile(FRONTIERS_FACTS).name == "frontiers"


def test_no_match_names_the_closest_profile_and_what_failed() -> None:
    facts = DocumentFacts(fonts=frozenset({"MinionPro-Regular"}), text="nature.com")

    with pytest.raises(NoProfileMatch, match="closest is 'frontiers'") as caught:
        select_profile(facts)

    assert "font MuseoSans" in str(caught.value)


def test_producer_and_creator_criteria_count(data: dict[str, Any]) -> None:
    data["match"]["producer"] = "^pikepdf"
    profile = build_profile(data, "t")

    assert select_profile(_with(producer="pikepdf 9"), (profile,)) is profile
    with pytest.raises(NoProfileMatch):
        select_profile(_with(producer="Acrobat"), (profile,))


def _with(**facts: str) -> DocumentFacts:
    return DocumentFacts(fonts=FRONTIERS_FACTS.fonts, text=FRONTIERS_FACTS.text, **facts)
