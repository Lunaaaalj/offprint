"""The cover rendered in real Chromium: the DOM boxes, the pixels and the failure paths."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image
from test_cover_hero import figure_doc, flow_diagram, line_chart, scan_on_black

from offprint.cover import CoverLayoutError, CoverOptions, Hero, generate_cover, select_hero
from offprint.cover.generate import build_html, render
from offprint.cover.hero import SHADOW
from offprint.ir import Author, Document, License, Meta

pytestmark = pytest.mark.usefixtures("chromium")

MARGIN = 130

LONG_TITLE = (
    "Hierarchical multimodal transformer architectures for longitudinal prediction of "
    "neurodegenerative disease progression using structural imaging, metabolic imaging and "
    "clinical assessments across cohorts"
)[:200]

META = Meta(
    title="Artificial intelligence techniques for neuroimaging data: a review",
    authors=(Author(name="Y. Nibila"), Author(name="M. Sivagami")),
    journal="Front. Artif. Intell.",
    volume="9",
    article_id="1748985",
    year=2026,
    doi="10.3389/frai.2026.1748985",
    license=License(spdx="CC-BY-4.0"),
)
LONG_META = Meta(
    title=LONG_TITLE,
    authors=tuple(Author(name=f"Firstname Surname{i}") for i in range(12)),
    journal="Proceedings of the National Academy of Sciences of the United States of America",
    volume="120",
    article_id="e2301234120",
    year=2024,
    doi="10.1234/long",
    license=License(spdx="CC-BY-NC-ND-4.0"),
)


def picture(png: bytes) -> Image.Image:
    return Image.open(BytesIO(png))


def by_name(rendered) -> dict:
    return {element.name: element for element in rendered.elements}


def with_meta(doc: Document, meta: Meta) -> Document:
    return Document(meta=meta, blocks=doc.blocks, assets=doc.assets)


def test_a_cover_is_a_1600_by_2560_png() -> None:
    image = picture(generate_cover(Document(meta=META)))

    assert image.format == "PNG"
    assert image.size == (1600, 2560)


def test_a_long_title_and_twelve_authors_lay_out_without_overflow() -> None:
    assert len(LONG_META.title) == 200
    doc = with_meta(figure_doc(scan_on_black()), LONG_META)

    rendered = render(build_html(doc, CoverOptions(), select_hero(doc)))

    assert rendered.problems == []
    boxes = by_name(rendered)
    assert set(boxes) == {"kicker", "title", "authors", "citation", "imprint"}
    for element in boxes.values():
        left, top, right, bottom = element.ink
        assert right > left, element.name
        assert bottom > top, element.name
        assert left >= element.box[0] - 0.5, element.name
        assert top >= element.box[1] - 0.5, element.name
        assert right <= element.box[2] + 0.5, element.name
        assert bottom <= element.box[3] + 0.5, element.name


def test_nothing_is_drawn_outside_the_text_column_on_the_long_cover() -> None:
    """A check on pixels, which doesn't rely on the DOM boxes the checks read."""
    grey = np.asarray(picture(generate_cover(Document(meta=LONG_META))).convert("L"), dtype=int)
    background = int(Image.new("RGB", (1, 1), SHADOW).convert("L").getpixel((0, 0)))
    below_the_motif = grey[1600:]

    assert np.abs(below_the_motif[:, :MARGIN] - background).max() <= 1
    assert np.abs(below_the_motif[:, -MARGIN:] - background).max() <= 1


def test_a_long_title_shrinks_and_a_short_one_stays_large() -> None:
    short = by_name(render(build_html(Document(meta=META), CoverOptions(), None)))["title"]
    long = by_name(render(build_html(Document(meta=LONG_META), CoverOptions(), None)))["title"]

    assert long.ink[3] - long.ink[1] > short.ink[3] - short.ink[1]


def test_a_single_unbreakable_word_still_fits() -> None:
    meta = Meta(title="Pneumonoultramicroscopicsilicovolcanoconiosis" * 4)

    assert picture(generate_cover(Document(meta=meta))).size == (1600, 2560)


def test_a_title_too_long_for_any_size_fails_loudly() -> None:
    meta = Meta(title="neurodegenerative " * 120)

    with pytest.raises(CoverLayoutError) as caught:
        generate_cover(Document(meta=meta))

    assert "cover.overflow" in {problem.code for problem in caught.value.problems}
    assert "title" in str(caught.value)


def test_a_paper_with_no_figures_gets_a_motif_only_cover() -> None:
    doc = Document(meta=META)

    html = build_html(doc, CoverOptions(), None)
    grey = np.asarray(picture(generate_cover(doc)).convert("L"), dtype=int)

    assert "<img" not in html
    assert "<circle" in html
    motif_area = grey[250:1590, 150:1450]
    background = int(Image.new("RGB", (1, 1), SHADOW).convert("L").getpixel((0, 0)))
    assert (np.abs(motif_area - background) > 8).mean() > 0.002


def test_charts_alone_give_a_motif_only_cover_too() -> None:
    doc = with_meta(figure_doc(line_chart()), META)

    assert "<img" not in build_html(doc, CoverOptions(), None)
    assert picture(generate_cover(doc)).size == (1600, 2560)


def test_a_photo_ends_up_on_the_cover() -> None:
    doc = with_meta(figure_doc(scan_on_black()), META)
    with_hero = np.asarray(picture(generate_cover(doc)).convert("L"), dtype=int)
    without = np.asarray(picture(generate_cover(Document(meta=META))).convert("L"), dtype=int)

    centre = (slice(700, 1100), slice(600, 1000))
    assert with_hero[centre].mean() > without[centre].mean() + 40


def test_the_hero_rule_can_be_swapped() -> None:
    chosen = []

    def always_the_diagram(doc: Document) -> Hero:
        chosen.append(doc)
        return Hero(flow_diagram(), "f0", "diagram")

    doc = with_meta(figure_doc(scan_on_black()), META)

    picture(generate_cover(doc, CoverOptions(select_hero=always_the_diagram)))

    assert chosen == [doc]


def test_covers_are_deterministic() -> None:
    doc = with_meta(figure_doc(scan_on_black()), META)

    assert generate_cover(doc) == generate_cover(doc)


def test_the_kicker_comes_from_the_title_then_the_options_then_a_default() -> None:
    assert ">a review<" in build_html(Document(meta=META), CoverOptions(), None)
    assert ">Editorial<" in build_html(Document(meta=META), CoverOptions(kicker="Editorial"), None)
    assert ">Article<" in build_html(Document(meta=LONG_META), CoverOptions(), None)


def test_metadata_is_text_never_markup() -> None:
    meta = Meta(
        title="<script>document.body.remove()</script> A & B", authors=(Author(name="<b>"),)
    )

    html = build_html(Document(meta=meta), CoverOptions(), None)

    assert "<script>" not in html
    assert "&amp;" in html
    assert picture(generate_cover(Document(meta=meta))).size == (1600, 2560)


def test_the_title_stays_legible_in_the_final_greyscale_pixels() -> None:
    """Contrast from the screenshot alone, as an e-ink screen would show it."""
    doc = with_meta(figure_doc(scan_on_black()), LONG_META)
    rendered = render(build_html(doc, CoverOptions(), select_hero(doc)))
    grey = np.asarray(picture(rendered.png).convert("L"), dtype=float) / 255
    linear = np.where(grey <= 0.04045, grey / 12.92, ((grey + 0.055) / 1.055) ** 2.4)

    for name, element in by_name(rendered).items():
        left, top, right, bottom = (round(edge) for edge in element.ink)
        area = linear[top:bottom, left:right]
        dark, light = np.percentile(area, 1), np.percentile(area, 99.9)
        assert (light + 0.05) / (dark + 0.05) >= 4.5, name


def page_with(style: str, text: str = "Hello") -> str:
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#00FF00">
    <div data-text="probe" style="position:absolute;left:10px;top:10px;width:300px;height:80px;
      --fit-max:30;--fit-min:30;{style}"><div>{text}</div></div></body></html>"""


def test_the_contrast_check_fails_colours_that_only_differ_in_hue() -> None:
    rendered = render(page_with("color:#FF8800"))

    assert [problem.code for problem in rendered.problems] == ["cover.contrast"]


def test_the_contrast_check_passes_colours_that_differ_in_grey() -> None:
    assert render(page_with("color:#000000")).problems == []


def test_the_overflow_check_catches_a_real_browser_overflow() -> None:
    rendered = render(page_with("color:#000;white-space:nowrap", "wide " * 100))

    assert [problem.code for problem in rendered.problems] == ["cover.overflow"]


def test_the_overflow_check_catches_overflow_hidden_by_clipping() -> None:
    rendered = render(page_with("color:#000;overflow:hidden", "tall " * 400))

    assert "cover.overflow" in [problem.code for problem in rendered.problems]
