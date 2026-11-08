"""Text steps. Each case comes from `prototype/README.md`, "Text extraction", items 2 to 4."""

import pytest

from offprint.cleanup import (
    ScriptOptions,
    TextOptions,
    clean_text,
    collapse_whitespace,
    dehyphenate,
    expand_ligatures,
    fix_combining_marks,
    keep_hyphen_from_vocabulary,
    script_positions,
    separate_words,
    spans_to_runs,
    strip_control_characters,
    vocabulary,
)
from offprint.cleanup.text import excerpt
from offprint.extraction import Span
from offprint.ir import Bold, Italic, Sub, Sup, Text


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


# Subscripts and superscripts, from geometry (issue #38)

SCRIPTS = ScriptOptions(size_ratio=0.88, offset=0.7)
MAIN, SMALL = 10.0, 7.0


def placed(text: str, size: float, centre: float, **style: bool) -> Span:
    """A span of this size whose vertical centre is `centre`, on a line centred at 5."""
    return Span(
        text=text,
        bbox=(0.0, centre - size / 2, 10.0, centre + size / 2),
        page=1,
        size=size,
        **style,
    )


def body(text: str, **style: bool) -> Span:
    return placed(text, MAIN, 5.0, **style)


def low(text: str) -> Span:
    return placed(text, SMALL, 7.5)


def high(text: str) -> Span:
    return placed(text, SMALL, 2.5)


def scripted(*spans: Span) -> tuple:
    return spans_to_runs([script_positions(spans, SCRIPTS)])


def test_a_smaller_span_below_the_line_is_a_subscript() -> None:
    assert scripted(body("d"), low("k")) == (Text("d"), Sub((Text("k"),)))


def test_a_subscript_can_be_a_word() -> None:
    assert scripted(body("d"), low("model"), body(" is the width")) == (
        Text("d"),
        Sub((Text("model"),)),
        Text(" is the width"),
    )


def test_a_subscript_and_a_superscript_on_the_same_base_both_survive() -> None:
    assert scripted(body("W"), low("i"), high("Q")) == (
        Text("W"),
        Sub((Text("i"),)),
        Sup((Text("Q"),)),
    )


def test_an_exponent_is_a_superscript() -> None:
    assert scripted(body("10"), high("-9")) == (Text("10"), Sup((Text("-9"),)))


def test_a_footnote_mark_after_a_word_is_a_superscript() -> None:
    assert scripted(body("results"), high("1"), body(" show")) == (
        Text("results"),
        Sup((Text("1"),)),
        Text(" show"),
    )


def test_a_script_at_the_start_of_a_line_is_judged_against_the_text_after_it() -> None:
    assert scripted(high("1"), body("Corresponding author")) == (
        Sup((Text("1"),)),
        Text("Corresponding author"),
    )


def test_a_flagged_span_of_the_main_size_is_not_raised() -> None:
    # The `√` that PyMuPDF flags as a superscript.
    assert scripted(body("x = "), body("√", superscript=True), body("d")) == (Text("x = √d"),)


def test_a_small_span_on_the_line_is_not_a_script() -> None:
    assert scripted(body("A "), placed("SMALL", SMALL, 5.0), body(" B")) == (Text("A SMALL B"),)


def test_a_small_span_that_is_barely_off_the_line_is_not_a_script() -> None:
    assert scripted(body("d"), placed("k", SMALL, 5.5)) == (Text("dk"),)


def test_a_wrong_flag_on_a_small_span_on_the_line_is_cleared() -> None:
    assert scripted(body("d"), placed("k", SMALL, 5.0, superscript=True)) == (Text("dk"),)


def test_a_line_of_one_size_is_unchanged() -> None:
    spans = (body("plain "), body("text"))
    assert script_positions(spans, SCRIPTS) == spans


def test_the_thresholds_come_from_the_options() -> None:
    tight = ScriptOptions(size_ratio=0.5, offset=0.7)
    assert scripted_with(tight, body("d"), low("k")) == (Text("dk"),)
    wide = ScriptOptions(size_ratio=0.88, offset=3.0)
    assert scripted_with(wide, body("d"), low("k")) == (Text("dk"),)


def scripted_with(options: ScriptOptions, *spans: Span) -> tuple:
    return spans_to_runs([script_positions(spans, options)])


def test_a_subscript_flag_makes_a_subscript_run() -> None:
    assert spans_to_runs([[span("d"), span("k", subscript=True)]]) == (
        Text("d"),
        Sub((Text("k"),)),
    )


def test_the_space_after_a_subscript_stays_outside_it() -> None:
    assert scripted(body("x"), low("i"), body(" "), body("are")) == (
        Text("x"),
        Sub((Text("i"),)),
        Text(" are"),
    )


def test_punctuation_after_a_subscript_is_not_part_of_it() -> None:
    assert scripted(body("x"), low("1, "), body("y")) == (
        Text("x"),
        Sub((Text("1"),)),
        Text(", y"),
    )


def test_a_comma_inside_a_subscript_stays() -> None:
    assert scripted(body("a"), low("i,j"), body(" b")) == (
        Text("a"),
        Sub((Text("i,j"),)),
        Text(" b"),
    )


def test_a_script_of_only_punctuation_is_plain_text() -> None:
    assert scripted(body("x"), low(","), body(" y")) == (Text("x, y"),)


def test_an_excerpt_ends_at_a_word_and_says_it_was_cut() -> None:
    text = " ".join(["word"] * 40)

    shortened = excerpt(text, width=20)

    assert shortened == "word word word word…"
    assert len(shortened) <= 20
    assert excerpt("a short label") == "a short label"
    assert excerpt("  spaced \n out  ") == "spaced out"
