"""The on-disk cache: one directory per identifier, holding the source and a manifest.

Identifiers never become paths directly. A DOI can legally hold `/`, `..` and almost anything
else, so a directory name is a sanitised slug plus a hash of the identifier: readable, and unable
to leave the cache or to collide with another identifier.
"""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from offprint.ir import Document, IRFormatError, Meta, from_json, to_json
from offprint.sources.errors import CacheError
from offprint.sources.identify import ArxivId, Doi
from offprint.sources.model import Attempt, Lookup, Resolution

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
# The only names a source may have. A manifest naming anything else was tampered with.
SOURCE_FILES = frozenset(
    {"source.tar.gz", "source.tar", "source.tex.gz", "source.xml", "source.pdf"}
)
_UNSAFE = re.compile(r"[^a-z0-9.-]+")
_MAX_SLUG = 80


def entry_key(target: Doi | ArxivId) -> str:
    """The directory name for an identifier. Pure."""
    kind = "doi" if isinstance(target, Doi) else "arxiv"
    identifier = str(target)
    slug = _UNSAFE.sub("_", identifier.lower())[:_MAX_SLUG].strip("._-")
    digest = hashlib.sha256(identifier.encode("utf-8", "backslashreplace")).hexdigest()[:16]
    return f"{kind}-{slug}-{digest}"


def entry_dir(root: Path, target: Doi | ArxivId) -> Path:
    path = root / entry_key(target)
    if path.resolve().parent != root.resolve():
        raise CacheError(f"refusing a cache path outside {root}: {path}")
    return path


def store(
    root: Path, target: Doi | ArxivId, resolution: Resolution, filename: str, body: bytes
) -> Resolution:
    """Save a resolved source, the manifest last so a crash leaves no half-valid entry."""
    if filename not in SOURCE_FILES:
        raise CacheError(f"refusing to cache a source named {filename!r}")
    entry = entry_dir(root, target)
    entry.mkdir(parents=True, exist_ok=True)
    _write_atomic(entry / filename, body)
    manifest = _manifest(resolution, filename, body, root)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    _write_atomic(entry / MANIFEST_NAME, text.encode("utf-8"))
    return replace(resolution, path=entry / filename)


def load(root: Path, target: Doi | ArxivId) -> Resolution | None:
    """Read a cache entry. `None` if there isn't one, `CacheError` if it can't be trusted."""
    entry = entry_dir(root, target)
    try:
        text = (entry / MANIFEST_NAME).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        raise CacheError(_broken(entry, str(error))) from error

    try:
        manifest = json.loads(text)
        if manifest["manifest_version"] != MANIFEST_VERSION:
            raise CacheError(_broken(entry, "unknown manifest version"))
        filename = manifest["file"]
        if filename not in SOURCE_FILES:
            raise CacheError(_broken(entry, f"bad file name {filename!r}"))
        path = entry / filename
        if _sha256(path.read_bytes()) != manifest["sha256"]:
            raise CacheError(_broken(entry, f"{filename} doesn't match its checksum"))
        return Resolution(
            input=manifest["input"],
            attempts=tuple(Attempt(**item) for item in manifest["attempts"]),
            lookups=tuple(Lookup(**item) for item in manifest["lookups"]),
            meta=_decode_meta(manifest["meta"], root),
            path=path,
            tier=manifest["tier"],
            from_cache=True,
        )
    except OSError as error:
        raise CacheError(_broken(entry, str(error))) from error
    except (ValueError, KeyError, TypeError, IRFormatError) as error:
        raise CacheError(_broken(entry, f"bad manifest ({error})")) from error


def _manifest(
    resolution: Resolution, filename: str, body: bytes, assets_dir: Path
) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "input": resolution.input,
        "tier": resolution.tier,
        "file": filename,
        "sha256": _sha256(body),
        "attempts": [asdict(attempt) for attempt in resolution.attempts],
        "lookups": [asdict(lookup) for lookup in resolution.lookups],
        "meta": _encode_meta(resolution.meta, assets_dir),
    }


def _encode_meta(meta: Meta | None, assets_dir: Path) -> Any:
    # A Document with no blocks or assets touches nothing in `assets_dir`.
    return None if meta is None else json.loads(to_json(Document(meta=meta), assets_dir))


def _decode_meta(value: Any, assets_dir: Path) -> Meta | None:
    return None if value is None else from_json(json.dumps(value), assets_dir).meta


def _write_atomic(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _broken(entry: Path, why: str) -> str:
    return f"cache entry {entry} is damaged: {why}. Run `offprint resolve --refresh`."
