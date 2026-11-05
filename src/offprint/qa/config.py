"""The gate's thresholds, read from `thresholds.yaml`, so no check holds a number of its own."""

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True, slots=True, kw_only=True)
class QaConfig:
    coverage_threshold: float
    min_word_letters: int
    worst_pages: int
    reference_headers: tuple[str, ...]
    year_pattern: str
    foreign_caption_overlap: float
    epubcheck_timeout: float
    warn_weight: float


def _build(data: dict[str, Any]) -> QaConfig:
    coverage = data["coverage"]
    tables = data["tables"]
    return QaConfig(
        coverage_threshold=coverage["threshold"],
        min_word_letters=coverage["min_word_letters"],
        worst_pages=coverage["worst_pages"],
        reference_headers=tuple(tables["reference_headers"]),
        year_pattern=tables["year_pattern"],
        foreign_caption_overlap=data["figures"]["foreign_caption_overlap"],
        epubcheck_timeout=data["epubcheck"]["timeout_seconds"],
        warn_weight=data["score"]["warn_weight"],
    )


@cache
def load_config() -> QaConfig:
    text = (resources.files(__package__) / "thresholds.yaml").read_text(encoding="utf-8")
    return _build(yaml.safe_load(text))
