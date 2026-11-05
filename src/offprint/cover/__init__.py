"""Cover generator: build a book cover from the IR's metadata and a hero image (#8)."""

from offprint.cover.generate import CoverLayoutError, CoverOptions, font_faces, generate_cover
from offprint.cover.hero import Hero, HeroSelector, select_hero

__all__ = [
    "CoverLayoutError",
    "CoverOptions",
    "Hero",
    "HeroSelector",
    "font_faces",
    "generate_cover",
    "select_hero",
]
