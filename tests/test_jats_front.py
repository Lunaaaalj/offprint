"""`<front>` to `Meta`."""

import pytest
from lxml import etree

from offprint.adapters.jats.front import (
    license_spdx,
    publication_year,
    read_abstract,
    read_authors,
    read_keywords,
    read_license,
    read_meta,
)
from offprint.ir import Author, Bold, License, Problem, Text

XLINK = 'xmlns:xlink="http://www.w3.org/1999/xlink"'
ALI = 'xmlns:ali="http://www.niso.org/schemas/ali/1.0/"'


def meta(inner: str) -> etree._Element:
    return etree.fromstring(f"<article-meta {XLINK} {ALI}>{inner}</article-meta>")


def author(surname: str, attributes: str = "", inner: str = "") -> str:
    return (
        f'<contrib contrib-type="author" {attributes}><name><surname>{surname}</surname>'
        f"<given-names>A.</given-names></name>{inner}</contrib>"
    )


def test_a_whole_front() -> None:
    article = etree.fromstring(
        f"""<article {XLINK} xml:lang="en"><front>
        <journal-meta><journal-title-group><journal-title>J</journal-title></journal-title-group>
        </journal-meta>
        <article-meta>
          <article-id pub-id-type="doi">10.1/x</article-id>
          <article-id pub-id-type="arxiv">2401.01234</article-id>
          <title-group><article-title>Main <italic>title</italic></article-title>
            <subtitle>sub</subtitle></title-group>
          <volume>9</volume><elocation-id>17</elocation-id>
          <abstract><p>Abstract one.</p><p>Two.</p></abstract>
        </article-meta></front><body/></article>"""
    )

    found = read_meta(article, [])

    assert found.title == "Main title: sub"
    assert found.journal == "J"
    assert (found.volume, found.article_id) == ("9", "17")
    assert (found.doi, found.arxiv_id) == ("10.1/x", "2401.01234")
    assert found.abstract == (Text("Abstract one."), Text(" "), Text("Two."))
    assert found.source_tier == "jats"


def test_no_article_meta_is_reported() -> None:
    problems: list[Problem] = []

    found = read_meta(etree.fromstring("<article><body/></article>"), problems)

    assert found.title == ""
    assert problems[0].code == "jats.no_front"


def test_authors_get_the_affiliations_they_point_to() -> None:
    xml = (
        "<contrib-group>"
        + author("One", inner='<xref rid="a1" ref-type="aff"/>')
        + author("Two", inner='<xref rid="a1 a2" ref-type="aff"/>')
        + "</contrib-group>"
        '<aff id="a1"><label>1</label><institution>Inst</institution>, <city>City</city></aff>'
        '<aff id="a2"><institution>Other</institution></aff>'
    )

    assert read_authors(meta(xml)) == (
        Author(name="A. One", affiliation="Inst, City"),
        Author(name="A. Two", affiliation="Inst, City; Other"),
    )


def test_a_lone_affiliation_applies_to_everyone() -> None:
    xml = author("One") + '<aff id="a"><institution>Inst</institution></aff>'

    assert read_authors(meta(xml))[0].affiliation == "Inst"


def test_tagged_affiliation_parts_get_commas() -> None:
    xml = (
        author("One", inner='<xref rid="a" ref-type="aff"/>')
        + '<aff id="a"><institution>Inst</institution><city>City</city>'
        "<country>Country</country></aff>"
    )

    assert read_authors(meta(xml))[0].affiliation == "Inst, City, Country"


def test_an_email_in_an_affiliation_stays_out() -> None:
    xml = author("One") + '<aff id="a"><institution>Inst</institution>, <email>x@y.z</email></aff>'

    assert read_authors(meta(xml))[0].affiliation == "Inst"


@pytest.mark.parametrize(
    "corresponding",
    [author("One", 'corresp="yes"'), author("One", inner='<xref ref-type="corresp" rid="c"/>')],
)
def test_the_corresponding_author(corresponding: str) -> None:
    assert read_authors(meta(corresponding))[0].corresponding


def test_a_collaboration_can_be_an_author() -> None:
    xml = '<contrib contrib-type="author"><collab>The Group</collab></contrib>'

    assert read_authors(meta(xml))[0].name == "The Group"


def test_editors_are_not_authors() -> None:
    xml = '<contrib contrib-type="editor"><name><surname>E</surname></name></contrib>'

    assert read_authors(meta(xml)) == ()


def test_the_article_date_beats_the_collection() -> None:
    xml = (
        '<pub-date date-type="collection"><year>2025</year></pub-date>'
        '<pub-date date-type="pub"><year>2026</year></pub-date>'
    )

    assert publication_year(meta(xml)) == 2026


def test_any_date_is_better_than_none() -> None:
    assert publication_year(meta('<pub-date date-type="x"><year>2020</year></pub-date>')) == 2020
    assert publication_year(meta("")) is None


@pytest.mark.parametrize(
    ("url", "spdx"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("http://creativecommons.org/licenses/by-nc-nd/3.0/igo/", "CC-BY-NC-ND-3.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("https://example.com/terms", None),
    ],
)
def test_license_spdx(url: str, spdx: str | None) -> None:
    assert license_spdx(url) == spdx


def test_the_fixtures_license_is_an_ali_ref() -> None:
    xml = (
        "<permissions><copyright-holder>A and B</copyright-holder><license>"
        "<ali:license_ref>https://creativecommons.org/licenses/by/4.0/</ali:license_ref>"
        "</license></permissions>"
    )

    assert read_license(meta(xml), []) == License(spdx="CC-BY-4.0", holder="A and B")


@pytest.mark.parametrize(
    "xml",
    [
        '<license xlink:href="https://creativecommons.org/licenses/by/4.0/"/>',
        '<license><license-p><ext-link xlink:href="https://creativecommons.org/licenses/by/4.0/">'
        "CC BY</ext-link></license-p></license>",
    ],
)
def test_other_places_a_license_url_sits(xml: str) -> None:
    found = read_license(meta(f"<permissions>{xml}</permissions>"), [])

    assert found is not None and found.spdx == "CC-BY-4.0"


def test_a_license_with_no_known_url_is_reported_not_guessed() -> None:
    problems: list[Problem] = []
    xml = (
        "<permissions><license><license-p>All rights reserved.</license-p></license></permissions>"
    )

    assert read_license(meta(xml), problems) is None
    assert problems[0].code == "jats.license_unknown"


def test_no_permissions_is_not_a_problem() -> None:
    problems: list[Problem] = []

    assert read_license(meta(""), problems) is None
    assert problems == []


def test_a_structured_abstract_keeps_its_labels() -> None:
    xml = (
        "<abstract><sec><title>Aims</title><p>To test.</p></sec>"
        "<sec><title>Methods</title><p>We did.</p></sec></abstract>"
    )

    assert read_abstract(meta(xml), []) == (
        (Bold((Text("Aims"),)), Text(" "), Text("To test.")),
        (Bold((Text("Methods"),)), Text(" "), Text("We did.")),
    )


def test_the_main_abstract_beats_a_graphical_one() -> None:
    xml = (
        '<abstract abstract-type="graphical"><p>No.</p></abstract><abstract><p>Yes.</p></abstract>'
    )

    assert read_abstract(meta(xml), []) == ((Text("Yes."),),)


def test_keywords_in_another_language_stay_out() -> None:
    xml = (
        '<kwd-group xml:lang="en"><kwd>one</kwd><kwd>one</kwd></kwd-group>'
        '<kwd-group xml:lang="es"><kwd>uno</kwd></kwd-group><kwd-group><kwd>two</kwd></kwd-group>'
    )

    assert read_keywords(meta(xml), "en") == ("one", "two")
