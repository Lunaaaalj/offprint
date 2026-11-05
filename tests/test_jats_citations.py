"""`<ref>` to a `Reference`. The mixed citations are shapes from the fixture."""

from lxml import etree

from offprint.adapters.jats.citations import reference_doi, reference_runs
from offprint.ir import Italic, Text
from offprint.render.epub.xhtml import plain_text


def ref(inner: str) -> etree._Element:
    return etree.fromstring(f'<ref id="B1">{inner}</ref>')


def text(inner: str) -> str:
    return plain_text(reference_runs(ref(inner), []))


NAMES = (
    "<person-group><name><surname>Abuhmed</surname><given-names>T.</given-names></name>\n"
    "<name><surname>Alonso</surname><given-names>J. M.</given-names></name></person-group>"
)


def test_a_mixed_citation_keeps_its_punctuation_and_gains_the_authors() -> None:
    xml = (
        f"<mixed-citation>{NAMES} (<year>2021</year>). <article-title>Robust</article-title>. "
        "<source>Knowl. Syst.</source> <volume>213</volume>:<fpage>106688</fpage>. doi: "
        '<pub-id pub-id-type="doi">10.1/x</pub-id></mixed-citation>'
    )

    assert text(xml) == (
        "Abuhmed, T., Alonso, J. M. (2021). Robust. Knowl. Syst. 213:106688. doi: 10.1/x"
    )


def test_the_journal_is_italic() -> None:
    runs = reference_runs(ref("<mixed-citation><source>J</source></mixed-citation>"), [])

    assert runs == (Italic((Text("J"),)),)


def test_bare_pubmed_ids_dont_run_into_the_doi() -> None:
    xml = (
        'doi: <pub-id pub-id-type="doi">10.1/x</pub-id><pub-id pub-id-type="pmid">35751201</pub-id>'
        '<pub-id pub-id-type="pmcid">PMC1</pub-id>'
    )

    assert text(f"<mixed-citation>{xml}\n</mixed-citation>") == "doi: 10.1/x"


def test_a_group_author_after_the_names() -> None:
    xml = (
        "<person-group><name><surname>A</surname><given-names>B.</given-names></name> "
        "The Initiative</person-group>"
    )

    assert text(f"<mixed-citation>{xml}</mixed-citation>") == "A, B., The Initiative"


def test_et_al() -> None:
    xml = "<person-group><name><surname>A</surname></name><etal/></person-group>"

    assert text(f"<mixed-citation>{xml}</mixed-citation>") == "A, et al."


def test_an_element_citation_is_composed() -> None:
    xml = (
        '<element-citation publication-type="journal"><person-group person-group-type="author">'
        "<name><surname>Smith</surname><given-names>J</given-names></name></person-group>"
        "<article-title>A title</article-title><source>Journal</source><year>2020</year>"
        "<volume>12</volume><issue>3</issue><fpage>1</fpage><lpage>9</lpage>"
        '<pub-id pub-id-type="doi">10.1/x</pub-id></element-citation>'
    )

    assert text(xml) == "Smith, J (2020). A title. Journal 12(3), 1–9."


def test_a_book_has_no_article_title() -> None:
    xml = "<element-citation><source>A Book</source><year>2020</year></element-citation>"

    assert text(xml) == "(2020). A Book"


def test_a_numbered_reference_keeps_its_label() -> None:
    assert text("<label>1.</label><mixed-citation>A paper</mixed-citation>") == "1. A paper"


def test_the_first_of_alternative_citations_is_used() -> None:
    xml = (
        "<citation-alternatives><mixed-citation>Mixed</mixed-citation>"
        "<element-citation><source>Element</source></element-citation></citation-alternatives>"
    )

    assert text(xml) == "Mixed"


def test_a_ref_with_no_citation_keeps_its_text() -> None:
    assert text("<note><p>Personal communication</p></note>") == "Personal communication"


def test_the_doi() -> None:
    assert reference_doi(ref('<pub-id pub-id-type="doi"> 10.1/x </pub-id>')) == "10.1/x"
    assert reference_doi(ref('<pub-id pub-id-type="pmid">1</pub-id>')) is None
