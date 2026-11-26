"""`meta.required` says what can still find a missing licence (#60)."""

from offprint.ir import Author, Document, License, Meta
from offprint.qa.checks import meta_required

AUTHORS = (Author(name="A"),)


def messages(meta: Meta) -> list[str]:
    return [item.message for item in meta_required(Document(meta=meta)).findings]


def test_an_arxiv_id_names_the_resolve_command() -> None:
    [message] = messages(Meta(title="T", authors=AUTHORS, arxiv_id="2611.09197", doi="10.1/x"))

    assert message.startswith("the paper has no license: ")
    assert "run `offprint resolve arXiv:2611.09197 --refresh`, then convert again" in message
    assert "arXiv lists no open license" in message


def test_a_doi_names_converting_the_resolved_doi() -> None:
    [message] = messages(Meta(title="T", authors=AUTHORS, doi="10.1/x"))

    assert "run `offprint resolve 10.1/x`, then convert `10.1/x` instead of a file" in message


def test_without_an_identifier_the_message_is_plain() -> None:
    assert messages(Meta(title="T", authors=AUTHORS)) == ["the paper has no license"]


def test_other_missing_fields_keep_their_messages() -> None:
    found = messages(Meta(title=" ", arxiv_id="2611.09197", license=License(spdx="CC-BY-4.0")))

    assert found == ["the paper has no title", "the paper has no author"]


def test_a_license_is_enough() -> None:
    assert messages(Meta(title="T", authors=AUTHORS, license=License(spdx="CC-BY-4.0"))) == []
