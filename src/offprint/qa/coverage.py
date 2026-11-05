"""`coverage.words`: how much of the source's text reached the book. Pure."""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set
from itertools import pairwise

from offprint.cleanup.geometry import centre, contains_point
from offprint.extraction import SourceEvidence, SourceText
from offprint.ir import BBox, Document, Equation, Figure
from offprint.qa.catalog import BY_ID
from offprint.qa.config import QaConfig
from offprint.qa.model import Finding, Outcome

_SAMPLE = 5


def word_list(text: str, min_letters: int) -> list[str]:
    """Return the words of at least `min_letters` letters, so that equal words compare equal.

    NFKC expands ligatures and undoes presentation forms, which a PDF has and an EPUB doesn't.
    """
    normal = unicodedata.normalize("NFKC", text.replace("\N{SOFT HYPHEN}", "")).casefold()
    return re.findall(rf"[^\W\d_]{{{min_letters},}}", normal)


def _image_boxes(doc: Document) -> dict[int, list[BBox]]:
    """Return the boxes of what the book shows as images, by page."""
    boxes: dict[int, list[BBox]] = {}
    for block in doc.blocks:
        place = doc.provenance.get(block.id)
        if isinstance(block, Figure | Equation) and place and place.page and place.bbox:
            boxes.setdefault(place.page, []).append(place.bbox)
    return boxes


def readable_texts(doc: Document, evidence: SourceEvidence) -> list[SourceText]:
    """Leave out text the source draws inside what the book has as an image.

    A figure's box includes its caption, which the book has as text, so captions stay.
    """
    images = _image_boxes(doc)

    def in_image(item: SourceText) -> bool:
        point = centre(item.bbox)
        if not any(contains_point(box, point) for box in images.get(item.page, ())):
            return False
        return not any(
            caption.page == item.page and contains_point(caption.bbox, point)
            for caption in evidence.captions
        )

    return [item for item in evidence.texts if not in_image(item)]


def _unplaced(words: Sequence[str], pairs: Set[tuple[str, str]], book: Set[str]) -> list[str]:
    """Return the words that aren't next to the same neighbour in the book.

    A common word is somewhere in the book even if its paragraph isn't, so this is what tells on
    which page the words went missing.
    """
    if len(words) < 2:
        return [word for word in words if word not in book]
    left = [False, *((a, b) in pairs for a, b in pairwise(words))]
    right = [*left[1:], False]
    return [word for word, *near in zip(words, left, right, strict=True) if not any(near)]


def _findings(
    missing: Mapping[int, Sequence[str]], lost: int, total: int, config: QaConfig
) -> tuple[Finding, ...]:
    severity = BY_ID["coverage.words"].severity
    worst = sorted(missing, key=lambda page: (-len(missing[page]), page))[: config.worst_pages]
    pages = tuple(
        Finding(
            check="coverage.words",
            message=(
                f"{len(missing[page])} words here aren't in the book: "
                + ", ".join(dict.fromkeys(missing[page][:_SAMPLE]))
            ),
            severity=severity,
            page=page,
        )
        for page in worst
    )
    overall = Finding(
        check="coverage.words",
        message=f"{lost} of {total} words didn't reach the book",
        severity=severity,
    )
    return (overall, *pages)


def word_coverage(
    doc: Document, evidence: SourceEvidence, book_text: Iterable[str], config: QaConfig
) -> Outcome:
    """Compare word by word, so a lost paragraph counts even if its words appear elsewhere."""
    book_words = [word_list(text, config.min_word_letters) for text in book_text]
    available = Counter(word for words in book_words for word in words)
    known = frozenset(available)
    pairs = {pair for words in book_words for pair in pairwise(words)}

    total = 0
    lost = 0
    missing: dict[int, list[str]] = {}
    for item in readable_texts(doc, evidence):
        words = word_list(item.text, config.min_word_letters)
        total += len(words)
        for word in words:
            if available[word] > 0:
                available[word] -= 1
            else:
                lost += 1
        if unplaced := _unplaced(words, pairs, known):
            missing.setdefault(item.page, []).extend(unplaced)

    value = (total - lost) / total if total else 1.0
    failed = value < config.coverage_threshold
    return Outcome(
        findings=_findings(missing, lost, total, config) if failed else (),
        value=value,
        threshold=config.coverage_threshold,
    )
