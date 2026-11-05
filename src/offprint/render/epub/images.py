"""Prepare the IR's assets for the EPUB: sniff the real format, downscale, gray equations."""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from offprint.ir import Asset

JPEG_QUALITY = 90
_MEDIA_TYPES = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg")}


class ImageError(ValueError):
    """An asset's bytes aren't an image Pillow can read."""


@dataclass(frozen=True, slots=True)
class EpubImage:
    data: bytes
    media_type: str
    extension: str
    converted_from: str | None = None


def prepare_image(asset: Asset, *, grayscale: bool, max_width: int | None) -> EpubImage:
    """Return `asset` as PNG or JPEG, keeping the original bytes if nothing has to change."""
    try:
        image = Image.open(io.BytesIO(asset.bytes))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise ImageError(f"asset {asset.id!r} isn't a readable image: {error}") from error

    source_format = image.format or "unknown"
    supported = source_format in _MEDIA_TYPES
    needs_resize = max_width is not None and image.width > max_width
    needs_gray = grayscale and image.mode not in ("L", "LA")
    if supported and not needs_resize and not needs_gray:
        return EpubImage(asset.bytes, *_MEDIA_TYPES[source_format])

    target_format = source_format if supported else "PNG"
    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    if grayscale:
        image = image.convert("LA" if has_alpha else "L")
    elif target_format == "JPEG":
        image = image.convert("RGB")
    elif image.mode not in ("L", "LA", "RGB", "RGBA"):
        # Palettes and bilevel images can't be resampled smoothly.
        image = image.convert("RGBA" if has_alpha else "RGB")
    if needs_resize:
        height = max(1, round(image.height * max_width / image.width))
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    if target_format == "JPEG":
        image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    else:
        image.save(buffer, "PNG", optimize=True)
    return EpubImage(
        buffer.getvalue(),
        *_MEDIA_TYPES[target_format],
        converted_from=None if supported else source_format,
    )
