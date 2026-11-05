"""What a screenshot goes through afterwards: the e-ink look, the bezel and the contact sheet.

These only approximate a Kindle, as `docs/preview.md` says. Pure, from images to images.
"""

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from offprint.preview.device import ContactSheetLayout

_PAPER = (236, 235, 229)
_INK = (22, 22, 24)
_BEZEL = (28, 28, 30)
_BEZEL_EDGE = (55, 55, 58)
_SHADOW = (0, 0, 0, 120)
_SHEET = (246, 246, 244)
_LABEL = (40, 40, 40)
_FLAG = (170, 30, 30)
_BEZEL_WIDTH = 110
_ROUNDING = 90
_SHADOW_MARGIN = 40
_SHADOW_BLUR = 28
_LABEL_SIZE = 14


def eink(screen: Image.Image) -> Image.Image:
    """Turn a screen grey on paper, with e-ink's tint and contrast."""
    gray = ImageOps.autocontrast(screen.convert("L"))
    return Image.composite(
        Image.new("RGB", gray.size, _PAPER), Image.new("RGB", gray.size, _INK), gray
    )


def with_bezel(screen: Image.Image) -> Image.Image:
    """Put a screen in a device with a soft shadow. It has no brand name on it."""
    width, height = screen.size
    margin = _SHADOW_MARGIN
    outer = (width + 2 * _BEZEL_WIDTH, height + 2 * _BEZEL_WIDTH)
    device = Image.new("RGBA", (outer[0] + 2 * margin, outer[1] + 2 * margin), (0, 0, 0, 0))
    box = (margin, margin, margin + outer[0], margin + outer[1])

    shadow = Image.new("RGBA", device.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + 15, box[2], box[3] + 15), _ROUNDING, fill=_SHADOW
    )
    device.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(_SHADOW_BLUR)))

    draw = ImageDraw.Draw(device)
    draw.rounded_rectangle(box, _ROUNDING, fill=_BEZEL, outline=_BEZEL_EDGE, width=3)
    device.paste(screen.convert("RGB"), (margin + _BEZEL_WIDTH, margin + _BEZEL_WIDTH))
    return device


def contact_sheet(
    pages: Sequence[tuple[Image.Image, str, str]], layout: ContactSheetLayout
) -> Image.Image:
    """Lay out thumbnails with labels under them. Each page is (image, label, flag label)."""
    columns = max(1, min(layout.columns, len(pages)))
    rows = (len(pages) + columns - 1) // columns
    thumbnails = [
        ImageOps.contain(image.convert("RGB"), (layout.thumbnail_width, 10_000))
        for image, _, _ in pages
    ]
    cell_height = max((image.height for image in thumbnails), default=0) + layout.label_height
    step_x = layout.thumbnail_width + layout.padding
    step_y = cell_height + layout.padding
    sheet = Image.new(
        "RGB",
        (columns * step_x + layout.padding, rows * step_y + layout.padding),
        _SHEET,
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(_LABEL_SIZE)
    for index, (thumbnail, (_, label, flag)) in enumerate(zip(thumbnails, pages, strict=True)):
        x = layout.padding + (index % columns) * step_x
        y = layout.padding + (index // columns) * step_y
        sheet.paste(thumbnail, (x, y))
        below = y + thumbnail.height + 6
        draw.text((x, below), label, fill=_LABEL, font=font)
        if flag:
            draw.text((x, below + _LABEL_SIZE + 4), flag, fill=_FLAG, font=font)
    return sheet
