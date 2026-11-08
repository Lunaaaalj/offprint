"""Paragraph joining, from `prototype/README.md` item 6."""

from offprint.cleanup import ParagraphOptions, drop_prefix, join_paragraphs, join_runs
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
        ParagraphOptions(loose_roles=("body",)),
    )

    assert text_of(doc) == ["as shown by Smith."]


def test_a_loose_role_does_not_loosen_the_others() -> None:
    doc = join_paragraphs(
        document(para("a", "no stop", role="small"), para("b", "Next entry", role="small")),
        ParagraphOptions(loose_roles=("body",)),
    )

    assert len(doc.blocks) == 2


def test_a_paragraph_that_starts_new_is_never_absorbed() -> None:
    doc = join_paragraphs(
        document(para("a", "the items are"), para("b", "• one")),
        ParagraphOptions(loose_roles=("body",), starts_new="^•"),
    )

    assert len(doc.blocks) == 2


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


def test_drop_prefix_removes_characters_across_runs() -> None:
    runs = (Text("FIGURE "), Italic((Text("1 A"),)), Text(" chart"))

    assert drop_prefix(runs, 9) == (Italic((Text("A"),)), Text(" chart"))


def test_drop_prefix_of_nothing_keeps_the_runs() -> None:
    runs = (Text("a"), Italic((Text("b"),)))

    assert drop_prefix(runs, 0) == runs


def test_drop_prefix_of_everything_is_empty() -> None:
    assert drop_prefix((Text("abc"),), 3) == ()


# Reference lists (issue #47)

REFERENCES = ParagraphOptions(reference_heading=r"^References$", entry_start=r"^\[\d+\]")


def heading(id: str, text: str) -> Heading:
    return Heading(id=id, level=1, runs=(Text(text),))


def test_a_reference_whose_first_line_ends_in_a_full_stop_stays_one_entry() -> None:
    doc = join_paragraphs(
        document(
            heading("h", "References"),
            para("a", "[12] Dzmitry Bahdanau. Neural machine translation by jointly learning."),
            para("b", "In International Conference on Learning Representations, 2017."),
            para("c", "[13] Jonas Gehring. Convolutional sequence to sequence learning."),
        ),
        REFERENCES,
    )

    assert text_of(doc) == [
        "[12] Dzmitry Bahdanau. Neural machine translation by jointly learning."
        " In International Conference on Learning Representations, 2017.",
        "[13] Jonas Gehring. Convolutional sequence to sequence learning.",
    ]


def test_a_line_that_starts_with_a_marker_starts_a_new_entry() -> None:
    doc = join_paragraphs(
        document(heading("h", "References"), para("a", "[1] A. B"), para("b", "[2] C. D")),
        REFERENCES,
    )

    assert text_of(doc) == ["[1] A. B", "[2] C. D"]


def test_the_entry_rule_only_applies_under_the_references_heading() -> None:
    doc = join_paragraphs(
        document(
            heading("h", "Discussion"),
            para("a", "The model works."),
            para("b", "Training took a day."),
        ),
        REFERENCES,
    )

    assert text_of(doc) == ["The model works.", "Training took a day."]


def test_a_later_heading_ends_the_reference_list() -> None:
    doc = join_paragraphs(
        document(
            heading("h", "References"),
            para("a", "[1] A. B."),
            heading("i", "Appendix"),
            para("b", "Extra material."),
            para("c", "More material."),
        ),
        REFERENCES,
    )

    assert text_of(doc) == ["[1] A. B.", "Extra material.", "More material."]


def test_without_an_entry_marker_references_join_as_before() -> None:
    options = ParagraphOptions(reference_heading=r"^References$")
    doc = join_paragraphs(
        document(heading("h", "References"), para("a", "Smith (2019) A paper."), para("b", "Roe.")),
        options,
    )

    assert text_of(doc) == ["Smith (2019) A paper.", "Roe."]
