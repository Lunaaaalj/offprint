"""JSON round-trip: every dataclass is tagged with its type, asset bytes live in a directory.

Asset files are named by SHA-256, never by id: ids come from adapters, so using them as paths
would allow traversal from a crafted JSON and collide on case-insensitive filesystems.
"""

import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from offprint.ir import model
from offprint.ir.model import Asset, Document

IR_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TYPES = {
    cls.__name__: cls
    for cls in vars(model).values()
    if isinstance(cls, type) and dataclasses.is_dataclass(cls)
}


class IRFormatError(ValueError):
    """The JSON or its asset directory can't be read back into a Document."""


def to_json(doc: Document, assets_dir: Path) -> str:
    """Serialize `doc`, writing its asset bytes into `assets_dir`."""
    payload = {"ir_version": IR_VERSION, "document": _encode(doc, assets_dir)}
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)


def from_json(text: str, assets_dir: Path) -> Document:
    """Rebuild a Document from `to_json` output and the same `assets_dir`."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise IRFormatError(f"not valid JSON: {error}") from error
    if not isinstance(payload, dict) or "document" not in payload:
        raise IRFormatError("not an IR file: no 'document' key")
    version = payload.get("ir_version")
    if version != IR_VERSION:
        raise IRFormatError(f"unsupported ir_version {version!r} (expected {IR_VERSION})")
    document = _decode(payload["document"], assets_dir)
    if not isinstance(document, Document):
        raise IRFormatError("'document' is not a Document")
    return document


def _encode(value: Any, assets_dir: Path) -> Any:
    if isinstance(value, Asset):
        return _encode_asset(value, assets_dir)
    if dataclasses.is_dataclass(value):
        encoded = {"type": type(value).__name__}
        for field in dataclasses.fields(value):
            item = getattr(value, field.name)
            if item != _default_of(field):
                encoded[field.name] = _encode(item, assets_dir)
        return encoded
    if isinstance(value, tuple | list):
        return [_encode(item, assets_dir) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item, assets_dir) for key, item in value.items()}
    return value


def _default_of(field: dataclasses.Field[Any]) -> Any:
    if field.default_factory is not dataclasses.MISSING:
        return field.default_factory()
    return field.default


def _encode_asset(asset: Asset, assets_dir: Path) -> dict[str, Any]:
    digest = hashlib.sha256(asset.bytes).hexdigest()
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / digest).write_bytes(asset.bytes)
    encoded = {"type": "Asset", "id": asset.id, "mime": asset.mime, "sha256": digest}
    if asset.width is not None:
        encoded["width"] = asset.width
    if asset.height is not None:
        encoded["height"] = asset.height
    if asset.box is not None:
        encoded["box"] = _encode(asset.box, assets_dir)
    return encoded


def _decode(value: Any, assets_dir: Path) -> Any:
    if isinstance(value, list):
        return tuple(_decode(item, assets_dir) for item in value)
    if not isinstance(value, dict):
        return value
    tag = value.get("type")
    if not isinstance(tag, str):
        return {key: _decode(item, assets_dir) for key, item in value.items()}
    if tag == "Asset":
        return _decode_asset(value, assets_dir)
    cls = _TYPES.get(tag)
    if cls is None:
        raise IRFormatError(f"unknown type {tag!r}")
    fields = {key: _decode(item, assets_dir) for key, item in value.items() if key != "type"}
    try:
        return cls(**fields)
    except TypeError as error:
        raise IRFormatError(f"bad {tag}: {error}") from error


def _decode_asset(value: dict[str, Any], assets_dir: Path) -> Asset:
    fields = {key: _decode(item, assets_dir) for key, item in value.items() if key != "type"}
    digest = fields.pop("sha256", None)
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise IRFormatError(f"asset {value.get('id')!r}: bad sha256 {digest!r}")
    try:
        data = (assets_dir / digest).read_bytes()
    except OSError as error:
        raise IRFormatError(f"asset {value.get('id')!r}: can't read bytes: {error}") from error
    if hashlib.sha256(data).hexdigest() != digest:
        raise IRFormatError(f"asset {value.get('id')!r}: file doesn't match its sha256")
    try:
        return Asset(bytes=data, **fields)
    except TypeError as error:
        raise IRFormatError(f"bad Asset: {error}") from error
