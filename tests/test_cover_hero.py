"""Hero selection on synthetic photo-like, chart-like and diagram images, and the duotone."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from offprint.cover.hero import (
    HERO_BOX,
    SHADOW,
    assess,
    crop_to_panel,
    select_hero,
    treat_hero,
)
from offprint.ir import Asset, Document, Figure, Meta


def photo(size: tuple[int, int] = (640, 480), seed: int = 1) -> Image.Image:
    """Soft blobs with fine grain: continuous tone everywhere, like a scan or a photograph."""
    width, height = size
    rng = np.random.default_rng(seed)
    coarse = rng.normal(128, 70, (height // 16, width // 16, 3)).clip(0, 255).astype(np.uint8)
    blobs = Image.fromarray(coarse).resize(size, Image.Resampling.BICUBIC)
    grain = rng.normal(0, 9, (height, width, 3))
    return Image.fromarray((np.asarray(blobs, dtype=float) + grain).clip(0, 255).astype(np.uint8))


def scan_on_black(size: tuple[int, int] = (500, 600), seed: int = 2) -> Image.Image:
    """A bright textured oval on black, the shape of the fixture's MRI panels."""
    width, height = size
    texture = np.asarray(photo(size, seed).convert("L"), dtype=float)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((40, 40, width - 40, height - 40), fill=255)
    soft = np.asarray(mask.filter(ImageFilter.GaussianBlur(4)), dtype=float) / 255
    return Image.fromarray((texture * soft).astype(np.uint8)).convert("RGB")


def bar_chart(size: tuple[int, int] = (640, 480)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.line((80, 40, 80, 420), fill="black", width=2)
    draw.line((80, 420, 610, 420), fill="black", width=2)
    for i, top in enumerate((300, 180, 240, 90)):
        draw.rectangle((120 + i * 115, top, 200 + i * 115, 419), fill=(70, 110, 180))
    return image


def line_chart(size: tuple[int, int] = (640, 480)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(60, 420, 60):
        draw.line((60, y, 620, y), fill=(190, 190, 190))
    rng = np.random.default_rng(3)
    for colour in ("navy", "darkorange", "seagreen"):
        points = [(60 + x * 28, int(rng.uniform(70, 410))) for x in range(21)]
        draw.line(points, fill=colour, width=2)
    return image


def flow_diagram(size: tuple[int, int] = (640, 480)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for i, colour in enumerate(((170, 210, 240), (200, 230, 190), (250, 205, 170))):
        top = 40 + i * 145
        draw.rounded_rectangle(
            (120, top, 520, top + 100), radius=12, fill=colour, outline="black", width=2
        )
        draw.line((320, top + 100, 320, top + 145), fill="black", width=3)
    return image


def figure_doc(*images: Image.Image) -> Document:
    assets, blocks = {}, []
    for i, image in enumerate(images):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        assets[f"a{i}"] = Asset(id=f"a{i}", mime="image/png", bytes=buffer.getvalue())
        blocks.append(Figure(id=f"f{i}", number=str(i), asset=f"a{i}", caption=()))
    return Document(meta=Meta(title="T"), blocks=tuple(blocks), assets=assets)


@pytest.mark.parametrize("image", [photo(), scan_on_black()], ids=["photo", "scan"])
def test_continuous_tone_reads_as_a_photo(image: Image.Image) -> None:
    assert assess(image).kind == "photo"


@pytest.mark.parametrize("image", [bar_chart(), line_chart()], ids=["bars", "lines"])
def test_plots_read_as_charts(image: Image.Image) -> None:
    assert assess(image).kind == "chart"


def test_filled_boxes_read_as_a_diagram() -> None:
    assert assess(flow_diagram()).kind == "diagram"


def test_a_photo_beats_everything_wherever_it_sits() -> None:
    hero = select_hero(figure_doc(line_chart(), flow_diagram(), photo(), bar_chart()))

    assert hero is not None
    assert (hero.figure_id, hero.kind) == ("f2", "photo")


def test_the_photo_with_most_picture_wins() -> None:
    hero = select_hero(figure_doc(scan_on_black((300, 300)), photo()))

    assert hero is not None
    assert hero.figure_id == "f1"


def test_a_diagram_beats_a_chart() -> None:
    hero = select_hero(figure_doc(bar_chart(), flow_diagram(), line_chart()))

    assert hero is not None
    assert (hero.figure_id, hero.kind) == ("f1", "diagram")


def test_charts_alone_give_no_hero() -> None:
    assert select_hero(figure_doc(bar_chart(), line_chart())) is None


def test_no_figures_give_no_hero() -> None:
    assert select_hero(Document(meta=Meta(title="T"))) is None


def test_tiny_images_are_not_heroes() -> None:
    assert select_hero(figure_doc(photo((120, 120)))) is None


def test_an_image_pillow_cannot_read_is_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = figure_doc(photo())
    svg = Asset(id="svg", mime="image/svg+xml", bytes=b"<svg/>")
    doc = Document(
        meta=doc.meta,
        blocks=(Figure(id="fs", number="9", asset="svg", caption=()), *doc.blocks),
        assets={**doc.assets, "svg": svg},
    )

    hero = select_hero(doc)

    assert hero is not None
    assert hero.figure_id == "f0"
    assert "svg" in caplog.text


def test_transparent_images_are_read_against_white() -> None:
    diagram = flow_diagram().convert("RGBA")
    pixels = np.array(diagram)
    pixels[(pixels[..., :3] == 255).all(axis=-1), 3] = 0

    hero = select_hero(figure_doc(Image.fromarray(pixels)))

    assert hero is not None
    assert hero.kind == "diagram"
    assert hero.image.getpixel((0, 0)) == (255, 255, 255)


def panels(*images: Image.Image, gutter: int = 60) -> Image.Image:
    width = sum(image.width for image in images) + gutter * (len(images) + 1)
    height = max(image.height for image in images) + gutter * 2
    sheet = Image.new("RGB", (width, height), "white")
    left = gutter
    for image in images:
        sheet.paste(image, (left, gutter))
        left += image.width + gutter
    return sheet


def test_a_multi_panel_figure_crops_to_one_panel() -> None:
    panel = scan_on_black()

    crop = crop_to_panel(panels(panel, scan_on_black(seed=3), scan_on_black(seed=4)))

    assert crop.width <= panel.width
    assert crop.height <= panel.height
    assert crop.width > panel.width * 0.8


def test_close_panels_resolve_to_the_middle_one() -> None:
    scans = [scan_on_black(seed=seed) for seed in (2, 3, 4)]

    crop = crop_to_panel(panels(*scans)).convert("L")

    errors = [
        np.abs(
            np.asarray(scan.convert("L").resize(crop.size), dtype=float)
            - np.asarray(crop, dtype=float)
        ).mean()
        for scan in scans
    ]
    assert int(np.argmin(errors)) == 1


def test_a_white_panel_tag_is_painted_out() -> None:
    panel = scan_on_black()
    ImageDraw.Draw(panel).rectangle((440, 10, 485, 55), fill="white")

    crop = crop_to_panel(panels(panel))

    grey = np.asarray(crop.convert("L"))
    assert grey[: crop.height // 6, -crop.width // 6 :].max() < 200


def test_a_label_in_the_top_margin_does_not_stretch_the_crop() -> None:
    sheet = panels(scan_on_black())
    ImageDraw.Draw(sheet).rectangle((450, 45, 470, 62), outline="black")

    crop = crop_to_panel(sheet)

    assert crop.height < 560


def test_a_single_image_keeps_its_content() -> None:
    image = photo()

    assert crop_to_panel(image).size == image.size


def test_the_vignette_dissolves_into_the_background() -> None:
    treated = np.asarray(treat_hero(photo()))

    for corner in (treated[0, 0], treated[0, -1], treated[-1, 0], treated[-1, -1]):
        assert tuple(int(channel) for channel in corner) == SHADOW


def test_the_edges_all_the_way_round_dissolve() -> None:
    treated = np.asarray(treat_hero(photo()))
    shadow = np.array(SHADOW)

    for edge in (treated[0], treated[-1], treated[:, 0], treated[:, -1]):
        assert np.abs(edge.astype(int) - shadow).max() <= 1


def test_the_result_is_a_duotone() -> None:
    treated = np.asarray(treat_hero(photo()), dtype=float).reshape(-1, 3)
    shadow = np.array(SHADOW, dtype=float)
    spread = treated - shadow
    direction = spread[np.linalg.norm(spread, axis=1).argmax()]
    direction /= np.linalg.norm(direction)

    off_axis = spread - np.outer(spread @ direction, direction)
    assert np.linalg.norm(off_axis, axis=1).max() < 3


def test_a_white_figure_is_inverted_rather_than_glaring() -> None:
    treated = np.asarray(treat_hero(flow_diagram()), dtype=float)
    height, width = treated.shape[:2]
    white_gap = treated[height // 2 - 90, width // 2 - 280]

    assert white_gap.mean() < 60


@pytest.mark.parametrize("size", [(2000, 400), (400, 2000), (50, 50)])
def test_the_hero_fits_its_box(size: tuple[int, int]) -> None:
    treated = treat_hero(photo(size) if min(size) >= 64 else Image.new("RGB", size, "gray"))

    assert treated.width <= HERO_BOX[0]
    assert treated.height <= HERO_BOX[1]
    assert max(treated.width / HERO_BOX[0], treated.height / HERO_BOX[1]) == pytest.approx(
        1, abs=0.01
    )
