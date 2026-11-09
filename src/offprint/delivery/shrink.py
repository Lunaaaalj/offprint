"""Make an EPUB smaller by downscaling the images inside it."""

import zipfile
from pathlib import Path

from offprint.delivery.errors import DeliveryError
from offprint.ir import Asset
from offprint.render.epub.images import ImageError, prepare_image

_IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def shrink_epub(source: Path, target: Path, max_width: int) -> Path:
    """Copy `source` to `target`, with every PNG and JPEG wider than `max_width` downscaled.

    Entries keep their order, so `mimetype` stays first and uncompressed. An image that can't be
    read is copied as it is.
    """
    try:
        with zipfile.ZipFile(source) as before, zipfile.ZipFile(target, "w") as after:
            for info in before.infolist():
                data = before.read(info)
                mime = _IMAGES.get(Path(info.filename).suffix.lower())
                if mime is not None:
                    data = _downscale(info.filename, mime, data, max_width)
                stored = info.filename == "mimetype"
                after.writestr(
                    info.filename,
                    data,
                    compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                )
    except (OSError, zipfile.BadZipFile) as error:
        raise DeliveryError(f"can't shrink {source.name}: {error}") from error
    return target


def _downscale(name: str, mime: str, data: bytes, max_width: int) -> bytes:
    try:
        asset = Asset(id=name, mime=mime, bytes=data)
        return prepare_image(asset, grayscale=False, max_width=max_width).data
    except ImageError:
        return data
