"""What the QA gate reads from a JATS article, apart from the mapping, and what that catches."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from offprint.adapters.jats import collect_evidence, convert_jats, parse_article, read_evidence
from offprint.extraction import SourceEvidence, SourceText
from offprint.ir import Document, Equation, Figure, Heading, Meta, Table
from offprint.pipeline import convert_to_epub
from offprint.qa import QaReport, load_config, run_gate
from offprint.qa.coverage import word_coverage
from offprint.qa.report import to_markdown
from offprint.render.epub import render_epub

FIXTURE = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985"
XML = FIXTURE / "paper.xml"
XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'
MML = 'xmlns:mml="http://www.w3.org/1998/Math/MathML"'
FULL_META = b"""<front><article-meta><title-group><article-title>Title</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Author</surname>
<given-names>An</given-names></name></contrib></contrib-group>
<permissions><license><ali:license_ref xmlns:ali="http://www.niso.org/schemas/ali/1.0/">
https://creativecommons.org/licenses/by/4.0/</ali:license_ref></license></permissions>
</article-meta></front>"""


def evidence_of(body: str, back: str = "") -> SourceEvidence:
    xml = f"<article {XLINK} {MML}><body>{body}</body><back>{back}</back></article>"
    return collect_evidence(parse_article(xml.encode()))


def texts(evidence: SourceEvidence) -> list[str]:
    return [item.text for item in evidence.texts]


def numbers(evidence: SourceEvidence, kind: str) -> list[str]:
    return [caption.number for caption in evidence.captions if caption.kind == kind]


# Reading the text


def test_an_article_has_no_pages() -> None:
    evidence = evidence_of("<p>Words.</p>")

    assert evidence.pages is None
    assert evidence.texts[0].page is None
    assert evidence.texts[0].bbox is None


def test_cells_are_not_joined_into_one_word() -> None:
    table = "<table><tr><td>first</td><td>second</td></tr></table>"

    assert texts(evidence_of(table)) == ["first", "second"]


def test_inline_markup_stays_in_its_sentence() -> None:
    assert texts(evidence_of("<p>a <italic>word</italic> and <xref>another</xref></p>")) == [
        "a word and another"
    ]


def test_what_the_book_has_as_an_image_is_not_text() -> None:
    body = (
        "<p>Before <inline-formula><mml:math><mml:mi>hidden</mml:mi></mml:math></inline-formula> "
        "after</p><disp-formula><mml:math><mml:mtext>hidden</mml:mtext></mml:math></disp-formula>"
        '<fig><graphic xlink:href="f.jpg"><alt-text>hidden</alt-text></graphic></fig>'
    )

    assert texts(evidence_of(body)) == ["Before after"]


def test_an_element_nobody_knows_still_counts_as_text() -> None:
    assert texts(evidence_of("<wobble>Unknown words</wobble>")) == ["Unknown words"]


def test_text_is_placed_by_its_nearest_section() -> None:
    body = "<sec><title>Outer</title><p>one</p><sec><title>Inner</title><p>two</p></sec></sec>"
    back = "<ref-list><ref><mixed-citation>three</mixed-citation></ref></ref-list>"

    found = {item.text: item.section for item in evidence_of(body, back).texts}

    assert found["one"] == "Outer"
    assert found["two"] == "Inner"
    assert found["three"] == "References"


def test_the_title_abstract_and_keywords_count() -> None:
    xml = b"""<article><front><article-meta>
    <title-group><article-title>The title</article-title></title-group>
    <abstract><p>The abstract</p></abstract>
    <kwd-group><kwd>first</kwd><kwd>second</kwd></kwd-group>
    </article-meta></front><body><p>x</p></body></article>"""

    found = {item.text: item.section for item in collect_evidence(parse_article(xml)).texts}

    assert found["The title"] == "Title"
    assert found["The abstract"] == "Abstract"
    assert found["first"] == found["second"] == "Keywords"


def test_a_sub_article_counts_even_though_it_is_not_converted() -> None:
    xml = b"""<article><body><p>x</p></body><sub-article><body><p>Reply text</p></body>
    </sub-article></article>"""

    assert "Reply text" in texts(collect_evidence(parse_article(xml)))


# Reading the numbers


def test_floats_are_numbered_from_their_labels() -> None:
    body = (
        '<fig><label>Figure 2.</label><graphic xlink:href="a.jpg"/></fig>'
        "<table-wrap><label>Table S1</label><table><tr><td>x</td></tr></table></table-wrap>"
        "<disp-formula><label>(7)</label><mml:math/></disp-formula>"
    )
    evidence = evidence_of(body)

    assert numbers(evidence, "figure") == ["2"]
    assert numbers(evidence, "table") == ["S1"]
    assert [item.number for item in evidence.equations] == ["7"]


def test_unlabelled_equations_are_not_numbered() -> None:
    assert evidence_of("<disp-formula><mml:math/></disp-formula>").equations == ()


def test_numbers_match_the_ir_for_unusual_floats() -> None:
    body = (
        "<fig><graphic xlink:href='a.jpg'/></fig>"
        "<fig><label>Figure 1</label><graphic xlink:href='b.jpg'/><graphic xlink:href='c.jpg'/>"
        "</fig>"
        "<table-wrap><label>Table 1</label><graphic xlink:href='d.jpg'/></table-wrap>"
    )

    assert numbers(evidence_of(body), "figure") == ["U1", "1", "1.2", "Table 1"]


# The fixture


@pytest.fixture(scope="module")
def doc() -> Document:
    return convert_jats(XML).document


@pytest.fixture(scope="module")
def evidence() -> SourceEvidence:
    return read_evidence(XML)


def gate(doc: Document, evidence: SourceEvidence, path: Path) -> QaReport:
    return run_gate(doc, epub=render_epub(doc, path / "book.epub"), evidence=evidence)


def failed(report: QaReport) -> set[str]:
    return {item.id for item in report.checks if item.status == "fail"}


def without(doc: Document, *dropped: str) -> Document:
    blocks = tuple(block for block in doc.blocks if block.id not in dropped)
    provenance = {key: value for key, value in doc.provenance.items() if key not in dropped}
    return replace(doc, blocks=blocks, provenance=provenance)


def first(doc: Document, kind: type) -> str:
    return next(block.id for block in doc.blocks if isinstance(block, kind))


def test_the_fixture_shows_what_the_article_holds(evidence: SourceEvidence) -> None:
    assert sum(caption.kind == "figure" for caption in evidence.captions) == 24
    assert sum(caption.kind == "table" for caption in evidence.captions) == 20
    assert len(evidence.equations) == 18


def test_the_gate_compares_the_fixture_with_its_source(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    report = gate(doc, evidence, tmp_path)
    by_id = {item.id: item for item in report.checks}

    assert report.verdict == "pass"
    assert by_id["coverage.words"].status == "pass"
    assert by_id["coverage.words"].value >= by_id["coverage.words"].threshold


def test_losing_a_section_fails_coverage_and_names_it(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    start = next(
        index
        for index, block in enumerate(doc.blocks)
        if isinstance(block, Heading) and block.level == 1
    )
    ends = [
        index
        for index, block in enumerate(doc.blocks)
        if isinstance(block, Heading) and block.level == 1 and index > start
    ]
    # The section with the most blocks, so that the loss is past the threshold.
    starts = [start, *ends]
    size, begin, end = max(
        (after - before, before, after) for before, after in zip(starts, starts[1:], strict=False)
    )
    assert size > 0
    lost = [
        block.id
        for block in doc.blocks[begin:end]
        if not isinstance(block, Figure | Table | Equation)
    ]

    report = gate(without(doc, *lost), evidence, tmp_path)

    assert "coverage.words" in failed(report)
    findings = [item for item in report.findings if item.check == "coverage.words"]
    assert all(item.page is None for item in findings)
    assert any(" in '" in item.message for item in findings)


@pytest.mark.parametrize(
    ("kind", "check"),
    [(Figure, "counts.figures"), (Table, "counts.tables"), (Equation, "counts.equations")],
)
def test_losing_a_block_fails_its_count(
    kind: type, check: str, doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    last = [block.id for block in doc.blocks if isinstance(block, kind)][-1]

    report = gate(without(doc, last), evidence, tmp_path)

    assert check in failed(report)
    assert any("the source shows" in item.message for item in report.findings)


def test_a_figure_the_source_does_not_have_fails_its_count(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    figures = [block for block in doc.blocks if isinstance(block, Figure)]
    extra = replace(figures[-1], id="invented", number="99")
    changed = replace(
        doc,
        blocks=(*doc.blocks, extra),
        provenance={**doc.provenance, "invented": doc.provenance[figures[-1].id]},
    )

    assert "counts.figures" in failed(gate(changed, evidence, tmp_path))


def test_the_reader_sees_what_the_mapper_really_drops(tmp_path: Path) -> None:
    """`sec-meta` has no mapping, so this text is lost by the real adapter, not by a mutation."""
    words = " ".join(f"unmapped{chr(97 + i)}{chr(97 + j)}" for i in range(9) for j in range(9))
    article = (
        b"<article>"
        + FULL_META
        + b"<body><sec><title>One</title><sec-meta>"
        + words.encode()
        + b"</sec-meta><p>Short paragraph.</p></sec></body></article>"
    )
    path = tmp_path / "paper.xml"
    path.write_bytes(article)

    result = convert_to_epub(str(path), tmp_path / "out", cover=False)

    outcome = next(item for item in result.report.checks if item.id == "coverage.words")
    assert outcome.status == "fail"
    assert result.report.verdict == "review"


def test_a_skipped_check_says_why_in_the_report(tmp_path: Path) -> None:
    (tmp_path / "paper.xml").write_bytes(XML.read_bytes())
    source = FIXTURE / "graphics"
    (tmp_path / "graphics").symlink_to(source)

    convert_to_epub(str(tmp_path / "paper.xml"), tmp_path / "out", cover=False)

    report = json.loads((tmp_path / "out" / "paper.qa.json").read_text())
    jats_only = [item for item in report["checks"] if item["id"] == "figure.foreign_caption"]
    assert jats_only[0]["status"] == "skip"
    assert "no pages" in jats_only[0]["reason"]
    assert report["counts"]["pages"] is None


def test_the_report_of_a_source_without_pages_does_not_mention_them(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    text = to_markdown(gate(doc, evidence, tmp_path))

    assert "The source has" not in text
    assert "The book has 24 figures" in text


def test_words_lost_from_several_sections_are_listed_by_section() -> None:
    source = SourceEvidence(
        pages=None,
        texts=(
            SourceText(text="alpha bravo charlie", section="Methods"),
            SourceText(text="delta", section="Results"),
        ),
        captions=(),
        equations=(),
    )

    outcome = word_coverage(Document(meta=Meta(title="T")), source, ["nothing"], load_config())

    messages = [item.message for item in outcome.findings]
    assert messages[1].startswith("3 words in 'Methods' aren't in the book")
    assert messages[2].startswith("1 words in 'Results'")
    assert all(item.page is None for item in outcome.findings)
