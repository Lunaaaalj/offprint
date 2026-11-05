"""Parsing untrusted JATS: the wrapper, refused files and hostile XML."""

from pathlib import Path

import pytest

from offprint.adapters.jats import JatsError, parse_article
from offprint.adapters.jats.xml import collapse, local, text_of

ARTICLE = b"<article><front/><body><p>Text</p></body></article>"


def test_a_bare_article() -> None:
    assert local(parse_article(ARTICLE)) == "article"


def test_pmcs_wrapper_is_opened() -> None:
    wrapped = b'<?xml version="1.0"?><pmc-articleset>' + ARTICLE + b"</pmc-articleset>"

    assert local(parse_article(wrapped)) == "article"


def test_the_fixtures_doctype_is_not_fetched() -> None:
    doctype = (
        b'<!DOCTYPE pmc-articleset PUBLIC "-//NLM//DTD ARTICLE SET 2.0//EN" '
        b'"https://dtd.nlm.nih.gov/ncbi/pmc/articleset/nlm-articleset-2.0.dtd">'
    )

    article = parse_article(doctype + b"<pmc-articleset>" + ARTICLE + b"</pmc-articleset>")

    assert text_of(article.find("body")) == "Text"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not xml", "well-formed"),
        (b"<html><body/></html>", "<html>"),
        (b"<pmc-articleset/>", "found 0"),
        (b"<pmc-articleset>" + ARTICLE * 2 + b"</pmc-articleset>", "found 2"),
        (b"<article><front/></article>", "no <body>"),
    ],
)
def test_what_cant_be_read_says_why(data: bytes, message: str) -> None:
    with pytest.raises(JatsError, match=message):
        parse_article(data)


def test_an_external_entity_never_reads_a_local_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    xml = (
        f'<!DOCTYPE article [<!ENTITY leak SYSTEM "file://{secret}">]>'
        "<article><body><p>&leak;</p></body></article>"
    )

    with pytest.raises(JatsError, match="entities"):
        parse_article(xml.encode())


def test_entity_expansion_is_refused() -> None:
    laughs = "".join(f'<!ENTITY l{n} "{f"&l{n - 1};" * 10}">' for n in range(1, 10))
    xml = (
        f'<!DOCTYPE article [<!ENTITY l0 "lol">{laughs}]>'
        "<article><body><p>&l9;</p></body></article>"
    )

    with pytest.raises(JatsError):
        parse_article(xml.encode())


def test_comments_and_processing_instructions_leave_no_trace() -> None:
    article = parse_article(b"<article><body><p>one<!-- no --> two<?pi no?></p></body></article>")

    assert text_of(article.find("body")) == "one two"


def test_collapse_keeps_no_break_and_thin_spaces() -> None:
    assert collapse(" a \n\t b c d ") == "a b c d"


def test_text_of_can_leave_elements_out() -> None:
    article = parse_article(b"<article><body><label>1</label>after <b>bold</b></body></article>")

    assert text_of(article.find("body"), "label") == "after bold"
