"""Paragraph joining, from `prototype/README.md` item 6."""

from offprint.cleanup import ParagraphOptions, join_paragraphs, join_runs
from offprint.ir import (
    Block,
    Document,
    Equation,
    Figure,
    Heading,
    Italic,
    ListItem,
    MathInline,
    Meta,
    Paragraph,
    ParagraphRole,
    Provenance,
    Table,
    Text,
)


def para(id: str, text: str, role: ParagraphRole = "body") -> Paragraph:
    return Paragraph(id=id, runs=(Text(text),), role=role)


def document(*blocks: Block) -> Document:
    provenance = {b.id: Provenance(adapter="pdf", page=i + 1) for i, b in enumerate(blocks)}
    return Document(meta=Meta(title="T"), blocks=blocks, provenance=provenance)


def text_of(doc: Document) -> list[str]:
    return [block.runs[0].text for block in doc.blocks if isinstance(block, Paragraph)]


FIGURE = Figure(id="f", number="1", asset="a", caption=())
TABLE = Table(id="t", number="1", caption=(), header=(), rows=())


def test_an_unfinished_paragraph_absorbs_a_lowercase_one() -> None:
    doc = join_paragraphs(document(para("a", "The results of the"), para("b", "second study.")))

    assert text_of(doc) == ["The results of the second study."]


def test_a_broken_word_closes_up_across_the_join() -> None:
    doc = join_paragraphs(document(para("a", "the classifi-"), para("b", "cation task.")))

    assert text_of(doc) == ["the classification task."]


def test_the_hook_keeps_a_compound_across_the_join() -> None:
    options = ParagraphOptions(keep_hyphen=lambda left, right: True)

    doc = join_paragraphs(document(para("a", "well-"), para("b", "known")), options)

    assert text_of(doc) == ["well-known"]


def test_a_finished_paragraph_stays() -> None:
    doc = join_paragraphs(document(para("a", "Finished."), para("b", "lowercase start")))

    assert text_of(doc) == ["Finished.", "lowercase start"]


def test_a_capitalised_paragraph_stays_by_default() -> None:
    doc = join_paragraphs(document(para("a", "no full stop"), para("b", "New paragraph.")))

    assert len(doc.blocks) == 2


def test_a_capitalised_continuation_joins_when_allowed() -> None:
    doc = join_paragraphs(
        document(para("a", "as shown by"), para("b", "Smith.")),
        ParagraphOptions(require_lowercase=False),
    )

    assert text_of(doc) == ["as shown by Smith."]


def test_different_roles_stay_apart() -> None:
    doc = join_paragraphs(document(para("a", "body text"), para("b", "credits", role="small")))

    assert len(doc.blocks) == 2


def test_a_float_that_interrupts_a_sentence_moves_after_the_paragraph() -> None:
    doc = join_paragraphs(
        document(para("a", "text before"), FIGURE, TABLE, para("b", "and after."), para("c", "X."))
    )

    assert [block.id for block in doc.blocks] == ["a", "f", "t", "c"]
    assert text_of(doc)[0] == "text before and after."


def test_equations_are_never_merged_across() -> None:
    equation = Equation(id="e", alt="x = 1", asset="a")

    doc = join_paragraphs(document(para("a", "we get"), equation, para("b", "where x is big.")))

    assert [block.id for block in doc.blocks] == ["a", "e", "b"]


def test_headings_and_lists_stop_a_join() -> None:
    heading = Heading(id="h", level=1, runs=(Text("H"),))
    item = ListItem(id="l", runs=(Text("item"),))

    doc = join_paragraphs(
        document(para("a", "unfinished"), heading, para("b", "text"), item, para("c", "more"))
    )

    assert [block.id for block in doc.blocks] == ["a", "h", "b", "l", "c"]


def test_provenance_follows_the_merge() -> None:
    doc = join_paragraphs(document(para("a", "one"), para("b", "two"), para("c", "three")))

    assert set(doc.provenance) == {"a"}
    assert doc.provenance["a"].page == 1
    assert doc.provenance["a"].note == "joined b, c"


def test_the_input_is_not_changed() -> None:
    doc = document(para("a", "one"), para("b", "two"))

    join_paragraphs(doc)

    assert set(doc.provenance) == {"a", "b"} and len(doc.blocks) == 2


def test_join_runs_merges_plain_text() -> None:
    assert join_runs((Text("a"),), (Text("b"),)) == (Text("a b"),)


def test_join_runs_dehyphenates_inside_styling() -> None:
    joined = join_runs((Text("a "), Italic((Text("classifi-"),))), (Text("cation"),))

    assert joined == (Text("a "), Italic((Text("classifi"),)), Text("cation"))


def test_join_runs_leaves_math_alone() -> None:
    joined = join_runs((MathInline("x-"),), (Text("axis"),))

    assert joined == (MathInline("x-"), Text(" axis"))
