"""Cover generator: build a book cover from the IR's metadata and a hero image (#8)."""

from offprint.cover.generate import CoverLayoutError, CoverOptions, generate_cover
from offprint.cover.hero import Hero, HeroSelector, select_hero

__all__ = [
    "CoverLayoutError",
    "CoverOptions",
    "Hero",
    "HeroSelector",
    "generate_cover",
    "select_hero",
]
