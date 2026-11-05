"""Rendered equations on disk, addressed by everything that decides their pixels.

A hit returns what a fresh render would: the key covers the formula, the preamble, the settings
and the engine, and only complete renders are stored. A damaged entry is a miss.
"""

import base64
import binascii
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from offprint.equations.model import MathRequest, MathSettings, RenderedMath
from offprint.ir import MathBox

CACHE_SUBDIR = "math"
_ENTRY_VERSION = 1


def cache_key(request: MathRequest, preamble: str, settings: MathSettings, engine: str) -> str:
    """The SHA-256 of what shapes the image. Pure."""
    fields = {
        "version": _ENTRY_VERSION,
        "latex": request.latex,
        "display": request.display,
        "preamble": preamble,
        "settings": asdict(settings),
        "engine": engine,
    }
    text = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def load(root: Path, key: str) -> RenderedMath | None:
    try:
        entry = json.loads((root / f"{key}.json").read_text())
        return RenderedMath(
            png=base64.b64decode(entry["png"], validate=True),
            width=entry["width"],
            height=entry["height"],
            box=MathBox(**entry["box"]),
            system_font=entry["system_font"],
        )
    except (OSError, ValueError, KeyError, TypeError, binascii.Error):
        return None


def store(root: Path, key: str, rendered: RenderedMath) -> None:
    """Write an entry in one step, so a crash or a parallel run can't leave half of one."""
    entry = {
        "png": base64.b64encode(rendered.png).decode("ascii"),
        "width": rendered.width,
        "height": rendered.height,
        "box": asdict(rendered.box),
        "system_font": rendered.system_font,
    }
    root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(entry, file)
        os.replace(temporary, root / f"{key}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
