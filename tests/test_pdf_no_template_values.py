"""Design rule 2: everything specific to a template lives in a profile, not in adapter code."""

import ast
import re
from pathlib import Path

import pytest

from offprint import adapters

ADAPTER_DIR = Path(adapters.__file__).parent / "pdf"
SOURCES = sorted(ADAPTER_DIR.glob("*.py"))

# Index positions into a bbox and small counts. Anything else is a point size or a coordinate.
ALLOWED_NUMBERS = {0, 1, 2, 3}

FONT_NAMES = re.compile(
    r"minion|museo|calibri|mtex|mtsy|rmtmi|mtgu|times|helvetica|arial|cambria|garamond"
    r"|frontiers|frontiersin",
    re.IGNORECASE,
)
TEMPLATE_STRINGS = re.compile(r"FIGURE|TABLE|Continued|CITATION|COPYRIGHT|KEYWORDS|\bReferences\b")


def test_the_adapter_has_sources() -> None:
    assert {path.name for path in SOURCES} >= {"assemble.py", "extract.py", "__init__.py"}


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_font_names(path: Path) -> None:
    assert not FONT_NAMES.findall(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_point_sizes_or_coordinates(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    numbers = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value not in ALLOWED_NUMBERS
    ]

    assert not numbers


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_float_literals_at_all(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    floats = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float) and node.value != 0
    ]

    assert not floats


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: path.name)
def test_no_caption_or_section_words_in_string_values(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstrings = {ast.get_docstring(node, clean=False) for node in ast.walk(tree) if _has_doc(node)}

    assert not [s for s in strings if s not in docstrings and TEMPLATE_STRINGS.search(s)]


def _has_doc(node: ast.AST) -> bool:
    return isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)


def test_the_checks_would_catch_a_violation() -> None:
    assert FONT_NAMES.search('font.startswith("MinionPro")')
    assert 297.5 not in ALLOWED_NUMBERS and 9 not in ALLOWED_NUMBERS
