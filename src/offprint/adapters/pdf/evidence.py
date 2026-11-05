"""Read what a PDF itself shows, for the QA gate to check the conversion against.

This never looks at the IR. It keeps the text a reader would read, leaving out what the profile
excludes on purpose (running heads, chart labels, the first page's sidebar), so a word missing from
the book is one the conversion lost.
"""

import re
from collections.abc import Iterator, Sequence

from offprint.adapters.pdf.assemble import hyphen_rule, merge_caption_fragments, read_caption
from offprint.adapters.pdf.equations import is_display_equation, line_number
from offprint.adapters.pdf.extract import PageData
from offprint.adapters.pdf.layout import column_of
from offprint.adapters.pdf.roles import block_role, block_text, first_span
from offprint.cleanup import clean_text, dehyphenate, separate_words
from offprint.cleanup.text import KeepHyphen
from offprint.extraction import (
    SourceCaption,
    SourceEquation,
    SourceEvidence,
    SourceText,
    TextBlock,
)
from offprint.profiles.schema import Profile


def _in_reading_area(block: TextBlock, profile: Profile) -> bool:
    """Say whether a block is between the header and footer, and not in the dropped sidebar."""
    layout = profile.page
    if block.bbox[3] < layout.header_y or block.bbox[1] > layout.footer_y:
        return False
    sidebar = layout.sidebar
    if sidebar is None or block.page != sidebar.page or block.bbox[2] >= sidebar.x_max:
        return True
    return re.match(sidebar.keep, block_text(block)) is not None


def source_text(block: TextBlock, profile: Profile, keep_hyphen: KeepHyphen | None) -> str:
    """Return a block's text with words broken across lines joined, as the adapter joins them."""
    text = ""
    for line in block.lines:
        spans = separate_words(line.spans, profile.text.word_gap)
        piece = clean_text("".join(span.text for span in spans)).strip()
        if piece:
            text = dehyphenate(text, piece, keep_hyphen) if text else piece
    return text


def _texts(
    blocks: Sequence[TextBlock], profile: Profile, keep_hyphen: KeepHyphen | None
) -> Iterator[SourceText]:
    for block in blocks:
        role = block_role(block, profile)
        if role is None or role == "ignore" or not _in_reading_area(block, profile):
            continue
        text = source_text(block, profile, keep_hyphen)
        if text:
            yield SourceText(text=text, page=block.page, bbox=block.bbox)


def _captions(
    blocks: Sequence[TextBlock], profile: Profile, keep_hyphen: KeepHyphen | None
) -> Iterator[SourceCaption]:
    for block in blocks:
        caption = read_caption(block, profile, keep_hyphen)
        if caption is not None:
            yield SourceCaption(
                kind=caption.kind,
                number=caption.number,
                page=block.page,
                bbox=block.bbox,
                continued=re.search(profile.captions.continuation, caption.text) is not None,
            )


def _equations(blocks: Sequence[TextBlock], profile: Profile) -> Iterator[SourceEquation]:
    for block in blocks:
        if first_span(block) is None or block_role(block, profile) not in ("body", "small"):
            continue
        if not is_display_equation(block, column_of(block.bbox, profile.page), profile):
            continue
        for line in block.lines:
            number = line_number(line, profile)
            if number is not None:
                yield SourceEquation(number=number, page=block.page, bbox=block.bbox)


def collect_evidence(pages: Sequence[PageData], profile: Profile) -> SourceEvidence:
    """Collect a document's reading text, captions and equation numbers. Pure."""
    keep_hyphen = hyphen_rule(pages, profile)
    texts: list[SourceText] = []
    captions: list[SourceCaption] = []
    equations: list[SourceEquation] = []
    for page in pages:
        blocks = merge_caption_fragments(page.blocks, profile)
        texts.extend(_texts(blocks, profile, keep_hyphen))
        captions.extend(_captions(blocks, profile, keep_hyphen))
        equations.extend(_equations(blocks, profile))
    return SourceEvidence(
        pages=len(pages),
        texts=tuple(texts),
        captions=tuple(captions),
        equations=tuple(equations),
    )
