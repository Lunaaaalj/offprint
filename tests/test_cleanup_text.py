"""Text steps. Each case comes from `prototype/README.md`, "Text extraction", items 2 to 4."""

import pytest

from offprint.cleanup import (
    TextOptions,
    clean_text,
    collapse_whitespace,
    dehyphenate,
    expand_ligatures,
    fix_combining_marks,
    keep_hyphen_from_vocabulary,
    separate_words,
    spans_to_runs,
    strip_control_characters,
    vocabulary,
)
from offprint.extraction import Span
from offprint.ir import Bold, Italic, Sup, Text


def span(text: str, **style: bool) -> Span:
    return Span(text=text, bbox=(0.0, 0.0, 10.0, 10.0), page=1, **style)


# Ligatures


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("classiﬁcation", "classification"),
        ("ﬂow", "flow"),
        ("eﬀect", "effect"),
        ("eﬃcient", "efficient"),
        ("baﬄe", "baffle"),
    ],
)
def test_ligatures_expand(text: str, expected: str) -> None:
    assert expand_ligatures(text) == expected


def test_ligature_expansion_leaves_other_compatibility_characters_alone() -> None:
    # This is why the step isn't NFKC, which would flatten these.
    assert expand_ligatures("x² ™ ½ fi") == "x² ™ ½ fi"


# Combining marks


@pytest.mark.parametrize(
    ("text", "expected"),
    [("¸S", "Ş"), ("¸s", "ş"), ("Yi¸Sit", "YiŞit"), ("caf´e", "café"), ("Ş", "Ş")],
)
def test_marks_compose_with_their_letter(text: str, expected: str) -> None:
    assert fix_combining_marks(text) == expected


@pytest.mark.parametrize("text", ["¸", "x´", "´x", "¸1", "a ¸ b", "plain text"])
def test_a_mark_that_forms_no_letter_stays(text: str) -> None:
    assert fix_combining_marks(text) == text


# Control characters


def test_control_characters_are_stripped() -> None:
    assert strip_control_characters("chap\x01ter\x0b \x1f￾one\x7f") == "chapter one"


def test_lone_surrogates_are_stripped() -> None:
    assert strip_control_characters("a\ud83db") == "ab"


@pytest.mark.parametrize("text", ["tab\there", "new\nline", "cr\rhere", "Ş é — 𝛼"])
def test_legal_characters_stay(text: str) -> None:
    assert strip_control_characters(text) == text


# Whitespace


def test_whitespace_runs_collapse() -> None:
    assert collapse_whitespace("spaced   out \t\n text") == "spaced out text"


@pytest.mark.parametrize("text", ["one two", " leading", "trailing ", "tight"])
def test_single_spaces_and_edges_stay(text: str) -> None:
    assert collapse_whitespace(text) == text


def test_clean_text_applies_every_step() -> None:
    assert clean_text("classiﬁ\x01ed   by ¸Sen") == "classified by Şen"


# Dehyphenation


def test_a_lowercase_continuation_closes_the_word() -> None:
    assert dehyphenate("classifi-", "cation of") == "classification of"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("ADNI-", "Based methods"),  # Uppercase continuation.
        ("from 10-", "20 subjects"),  # Not a word.
        ("the value -", "next"),  # A dash, not a hyphen.
        ("ordinary", "text"),  # No hyphen.
    ],
)
def test_other_breaks_only_get_a_space(left: str, right: str) -> None:
    assert dehyphenate(left, right) == f"{left} {right}"


def test_the_hook_keeps_a_real_compound() -> None:
    joined = dehyphenate(
        "magnetization-", "prepared rapid", lambda a, b: (a, b) == ("magnetization", "prepared")
    )

    assert joined == "magnetization-prepared rapid"


def test_the_hook_sees_the_whole_compound_on_the_left() -> None:
    seen: list[tuple[str, str]] = []

    def hook(left: str, right: str) -> bool:
        seen.append((left, right))
        return False

    dehyphenate("a non-invasive-", "ly done", hook)

    assert seen == [("non-invasive", "ly")]


def test_vocabulary_keeps_two_known_words_apart() -> None:
    keep = keep_hyphen_from_vocabulary(["magnetization", "prepared"])

    assert keep("magnetization", "prepared")


def test_vocabulary_keeps_a_compound_seen_with_its_hyphen() -> None:
    keep = keep_hyphen_from_vocabulary(vocabulary(["a self-attention layer"]))

    assert keep("self", "attention")


def test_vocabulary_closes_up_a_word_it_knows_whole() -> None:
    keep = keep_hyphen_from_vocabulary(["in", "formation", "information"])

    assert not keep("in", "formation")


def test_vocabulary_prefers_the_closed_up_form_when_it_saw_both() -> None:
    keep = keep_hyphen_from_vocabulary(["multi-modal", "multimodal"])

    assert not keep("multi", "modal")


def test_vocabulary_closes_up_when_a_side_is_not_a_word() -> None:
    keep = keep_hyphen_from_vocabulary(["classification", "of"])

    assert not keep("classifi", "cation")


def test_vocabulary_ignores_case() -> None:
    assert vocabulary(["Deep Learning"]) == {"deep", "learning"}


# Word gaps


def at(text: str, x0: float, x1: float) -> Span:
    return Span(text=text, bbox=(x0, 0.0, x1, 8.0), page=1)


def test_a_visible_gap_between_spans_becomes_a_space() -> None:
    spans = [at("one", 0, 10), at("two", 15, 25)]

    assert [s.text for s in separate_words(spans)] == ["one ", "two"]


def test_touching_spans_stay_glued() -> None:
    spans = [at("clas", 0, 10), at("sify", 10.5, 25)]

    assert separate_words(spans) == tuple(spans)


def test_spans_that_already_have_a_space_get_no_second_one() -> None:
    spans = [at("one ", 0, 10), at("two", 15, 25), at(" three", 30, 40)]

    assert separate_words(spans) == tuple(spans)


# Spans to runs


def test_spans_become_styled_runs() -> None:
    lines = [[span("Plain "), span("italic", italic=True), span(" "), span("bold", bold=True)]]

    assert spans_to_runs(lines) == (
        Text("Plain "),
        Italic((Text("italic "),)),
        Bold((Text("bold"),)),
    )


def test_adjacent_spans_of_one_style_merge() -> None:
    assert spans_to_runs([[span("one "), span("two")]]) == (Text("one two"),)


def test_bold_italic_nests() -> None:
    assert spans_to_runs([[span("x", bold=True, italic=True)]]) == (Bold((Italic((Text("x"),)),)),)


def test_a_superscript_loses_its_spaces() -> None:
    assert spans_to_runs([[span("Smith"), span(" 1 ", superscript=True)]]) == (
        Text("Smith"),
        Sup((Text("1"),)),
    )


def test_lines_join_with_a_space() -> None:
    assert spans_to_runs([[span("first line")], [span("second line")]]) == (
        Text("first line second line"),
    )


def test_lines_dehyphenate_across_styles() -> None:
    lines = [[span("classifi-", italic=True)], [span("cation")]]

    assert spans_to_runs(lines) == (Italic((Text("classifi"),)), Text("cation"))


def test_lines_use_the_hyphen_hook() -> None:
    options = TextOptions(keep_hyphen=lambda left, right: True)

    assert spans_to_runs([[span("well-")], [span("known")]], options) == (Text("well-known"),)


def test_whitespace_only_lines_vanish() -> None:
    assert spans_to_runs([[span("   ")], [span("text")], [span(" ")]]) == (Text("text"),)


def test_span_text_is_cleaned() -> None:
    assert spans_to_runs([[span("  ﬁ\x01ne   text ")]]) == (Text("fine text"),)
