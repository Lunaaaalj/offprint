"""The cleanup step registry."""

from collections.abc import Iterator

import pytest

from offprint.cleanup import registry
from offprint.cleanup.registry import registered, step


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(registry, "_STEPS", {})
    yield


def test_a_step_is_listed_and_stays_callable() -> None:
    @step("double", "text")
    def double(text: str) -> str:
        return text * 2

    assert double("a") == "aa"
    assert [item.name for item in registered()] == ["double"]


def test_steps_can_be_filtered_by_stage() -> None:
    step("a", "text")(str)
    step("b", "table")(str)

    assert [item.name for item in registered("table")] == ["b"]


def test_a_duplicate_name_is_rejected() -> None:
    step("a", "text")(str)

    with pytest.raises(ValueError, match="'a'"):
        step("a", "table")(str)
