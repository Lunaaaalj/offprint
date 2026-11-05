"""Input detection: a pure function, so every shape of input is pinned here."""

from pathlib import PurePath

import pytest
from hypothesis import given
from hypothesis import strategies as st

from offprint.sources import ArxivId, Doi, InputError, LocalFile, detect_input


@pytest.mark.parametrize(
    ("text", "doi"),
    [
        ("10.3389/frai.2026.1748985", "10.3389/frai.2026.1748985"),
        ("  10.3389/frai.2026.1748985\n", "10.3389/frai.2026.1748985"),
        ("10.1016/J.CELL.2020.01.001", "10.1016/j.cell.2020.01.001"),
        ("doi:10.1000/xyz123", "10.1000/xyz123"),
        ("DOI: 10.1000/xyz123", "10.1000/xyz123"),
        ("https://doi.org/10.3389/frai.2026.1748985", "10.3389/frai.2026.1748985"),
        ("http://dx.doi.org/10.1000/xyz123", "10.1000/xyz123"),
        ("doi.org/10.1000/xyz123", "10.1000/xyz123"),
        ("https://doi.org/10.1000%2Fxyz123", "10.1000/xyz123"),
        ("https://doi.org/10.1000/xyz123?utm_source=x", "10.1000/xyz123"),
        ("10.1002/(SICI)1096-8644(199601)99:1<1::AID-AJPA1>3.0.CO;2-1",
         "10.1002/(sici)1096-8644(199601)99:1<1::aid-ajpa1>3.0.co;2-1"),
    ],
)  # fmt: skip
def test_dois(text: str, doi: str) -> None:
    assert detect_input(text) == Doi(doi)


@pytest.mark.parametrize(
    ("text", "base", "version"),
    [
        ("2401.01234", "2401.01234", None),
        ("2401.01234v2", "2401.01234", 2),
        ("0704.0001", "0704.0001", None),
        ("1412.9999v12", "1412.9999", 12),
        ("arXiv:2401.01234", "2401.01234", None),
        ("arxiv:hep-th/9901001", "hep-th/9901001", None),
        ("hep-th/9901001", "hep-th/9901001", None),
        ("hep-th/9901001v3", "hep-th/9901001", 3),
        ("cs/0112017", "cs/0112017", None),
        ("math.GT/0309136", "math/0309136", None),
        ("https://arxiv.org/abs/2401.01234", "2401.01234", None),
        ("http://arxiv.org/abs/2401.01234v3", "2401.01234", 3),
        ("https://www.arxiv.org/abs/2401.01234/", "2401.01234", None),
        ("https://export.arxiv.org/abs/hep-th/9901001", "hep-th/9901001", None),
        ("https://arxiv.org/pdf/2401.01234", "2401.01234", None),
        ("https://arxiv.org/pdf/2401.01234v2.pdf", "2401.01234", 2),
        ("https://arxiv.org/pdf/hep-th/9901001.pdf", "hep-th/9901001", None),
        ("arxiv.org/abs/2401.01234", "2401.01234", None),
        ("https://doi.org/10.48550/arXiv.2401.01234", "2401.01234", None),
        ("10.48550/arXiv.2401.01234v2", "2401.01234", 2),
    ],
)
def test_arxiv_ids(text: str, base: str, version: int | None) -> None:
    assert detect_input(text) == ArxivId(base, version)


@pytest.mark.parametrize(
    ("text", "tier"),
    [
        ("paper.pdf", "pdf"),
        ("/tmp/PAPER.PDF", "pdf"),
        ("some dir/article.xml", "jats"),
        ("source.tar.gz", "latex"),
        ("./10.1234/x.pdf", "pdf"),
        ("hep-th/9901001.pdf", "pdf"),
        ("2401.01234.pdf", "pdf"),
    ],
)
def test_local_files(text: str, tier: str) -> None:
    assert detect_input(text) == LocalFile(PurePath(text), tier)  # type: ignore[arg-type]


def test_a_doi_that_looks_like_a_file_is_a_doi() -> None:
    assert detect_input("10.1234/x.pdf") == Doi("10.1234/x.pdf")


def test_a_traversing_doi_is_still_syntactically_a_doi() -> None:
    # Detection accepts it, since DOIs may hold these characters. The cache has to cope.
    assert detect_input("10.1000/../../etc/passwd") == Doi("10.1000/../../etc/passwd")


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("paper.docx", "can't tell"),
        ("hello", "can't tell"),
        ("paper.tar", "can't tell"),
        ("10.12/too-short-prefix", "can't tell"),
        ("10.1000", "can't tell"),
        ("10.1000/", "can't tell"),
        ("10.1000/has space", "can't tell"),
        ("doi:", "not a DOI"),
        ("doi:11.1000/xyz", "not a DOI"),
        ("https://doi.org/", "not a DOI"),
        ("https://doi.org/not-a-doi", "not a DOI"),
        ("2413.01234", "month 13"),
        ("2400.01234", "month 00"),
        ("0703.0001", "April 2007"),
        ("2401.1234", "5 digits"),
        ("2401.012345", "5 digits"),
        ("1412.12345", "4 digits"),
        ("2401.01234v0", "versions start at v1"),
        ("arxiv:", "not an arXiv id"),
        ("arxiv:garbage", "not an arXiv id"),
        ("arxiv:2401.01234v", "not an arXiv id"),
        ("foo-bar/9901001", "no archive"),
        ("hep-th/9913001", "month 13"),
        ("hep-th/0805001", "no paper"),
        ("hep-th/9901000", "no paper"),
        ("hep-th/990100", "can't tell"),
        ("https://arxiv.org/list/hep-th/new", "unsupported arXiv URL"),
        ("https://arxiv.org/abs/", "unsupported arXiv URL"),
        ("https://arxiv.org/abs/not-an-id", "not an arXiv id"),
        ("https://example.com/paper.pdf", "unsupported URL"),
        ("https://arxiv.org.evil.example/abs/2401.01234", "unsupported URL"),
        ("ftp://doi.org/10.1000/xyz", "unsupported URL"),
        ("file:///etc/passwd.pdf", "unsupported URL"),
        ("http://[bad/10.1000/x", "not a valid URL"),
        ("10.1000/x\x00y", "control characters"),
        ("paper\n.pdf", "control characters"),
    ],
)
def test_malformed_inputs_say_what_is_wrong(text: str, complaint: str) -> None:
    with pytest.raises(InputError, match=complaint):
        detect_input(text)


@given(st.text(max_size=80))
def test_any_text_is_classified_or_refused_cleanly(text: str) -> None:
    try:
        detect_input(text)
    except InputError:
        pass


@given(st.sampled_from(["2401.01234", "hep-th/9901001", "1412.9999"]), st.integers(1, 99))
def test_str_round_trips(base: str, version: int) -> None:
    parsed = detect_input(f"{base}v{version}")
    assert detect_input(str(parsed)) == parsed
