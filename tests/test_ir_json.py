"""JSON round-trip of the Document IR."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import strategies as st

from offprint.ir import (
    Asset,
    Author,
    Bold,
    Cite,
    Document,
    Equation,
    Figure,
    Heading,
    IRFormatError,
    Italic,
    License,
    Link,
    ListItem,
    MathBox,
    MathInline,
    Meta,
    Paragraph,
    Provenance,
    Reference,
    Sub,
    Sup,
    Table,
    Text,
    from_json,
    to_json,
)

text = st.text(max_size=12)
maybe_text = st.none() | text
coordinate = st.floats(allow_nan=False, allow_infinity=False)
block_id = st.text(min_size=1, max_size=6)

leaf_runs = st.builds(Text, text) | st.builds(MathInline, text, maybe_text)
runs = st.recursive(
    st.lists(leaf_runs, max_size=3).map(tuple),
    lambda children: st.lists(
        leaf_runs
        | st.builds(Italic, children)
        | st.builds(Bold, children)
        | st.builds(Sup, children)
        | st.builds(Sub, children)
        | st.builds(Link, text, children)
        | st.builds(Cite, text, children),
        max_size=3,
    ).map(tuple),
    max_leaves=8,
)
cells = st.lists(runs, max_size=3).map(tuple)
blocks = st.one_of(
    st.builds(Heading, id=block_id, level=st.integers(0, 6), runs=runs, number=maybe_text),
    st.builds(
        Paragraph,
        id=block_id,
        runs=runs,
        role=st.sampled_from(["body", "abstract", "small", "meta"]),
    ),
    st.builds(ListItem, id=block_id, runs=runs, ordered=st.booleans(), depth=st.integers(0, 3)),
    st.builds(
        Equation, id=block_id, alt=text, number=maybe_text, latex=maybe_text, asset=maybe_text
    ),
    st.builds(Figure, id=block_id, number=text, asset=text, caption=runs, alt=maybe_text),
    st.builds(
        Table,
        id=block_id,
        number=text,
        caption=runs,
        header=cells,
        rows=st.lists(cells, max_size=3).map(tuple),
        notes=runs,
    ),
    st.builds(Reference, id=block_id, runs=runs, key=maybe_text, doi=maybe_text),
)
meta = st.builds(
    Meta,
    title=text,
    authors=st.lists(
        st.builds(Author, name=text, affiliation=maybe_text, corresponding=st.booleans()),
        max_size=3,
    ).map(tuple),
    journal=maybe_text,
    year=st.none() | st.integers(1000, 3000),
    volume=maybe_text,
    article_id=maybe_text,
    doi=maybe_text,
    arxiv_id=maybe_text,
    license=st.none() | st.builds(License, spdx=text, holder=maybe_text),
    abstract=runs,
    keywords=st.lists(text, max_size=3).map(tuple),
    source_tier=st.sampled_from([None, "latex", "jats", "pdf", "ml"]),
)
provenance = st.builds(
    Provenance,
    adapter=text,
    page=st.none() | st.integers(1, 500),
    bbox=st.none() | st.tuples(coordinate, coordinate, coordinate, coordinate),
    note=maybe_text,
)
assets = st.dictionaries(
    text,
    st.builds(
        Asset,
        id=text,
        mime=text,
        bytes=st.binary(max_size=16),
        width=st.none() | st.integers(1, 4000),
        height=st.none() | st.integers(1, 4000),
    ),
    max_size=3,
)
documents = st.builds(
    Document,
    meta=meta,
    blocks=st.lists(blocks, max_size=5).map(tuple),
    assets=assets,
    provenance=st.dictionaries(text, provenance, max_size=3),
)


@given(documents)
def test_generated_documents_survive_the_round_trip(doc: Document) -> None:
    with TemporaryDirectory() as directory:
        assets_dir = Path(directory)
        assert from_json(to_json(doc, assets_dir), assets_dir) == doc


def document_with_one_asset() -> Document:
    asset = Asset(id="fig-1", mime="image/png", bytes=b"\x89PNG")
    return Document(meta=Meta(title="T"), assets={"fig-1": asset})


def test_asset_bytes_live_beside_the_json_not_inside_it(tmp_path: Path) -> None:
    payload = json.loads(to_json(document_with_one_asset(), tmp_path))

    stored = payload["document"]["assets"]["fig-1"]
    assert "bytes" not in stored
    assert (tmp_path / stored["sha256"]).read_bytes() == b"\x89PNG"


def test_asset_ids_never_become_paths(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    asset = Asset(id="../escaped", mime="image/png", bytes=b"x")

    to_json(Document(meta=Meta(title="T"), assets={asset.id: asset}), assets_dir)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["assets"]


def test_a_crafted_sha256_cannot_read_outside_the_assets_dir(tmp_path: Path) -> None:
    payload = json.loads(to_json(document_with_one_asset(), tmp_path))
    payload["document"]["assets"]["fig-1"]["sha256"] = "../secret"

    with pytest.raises(IRFormatError, match="bad sha256"):
        from_json(json.dumps(payload), tmp_path)


def test_a_corrupted_asset_file_is_reported(tmp_path: Path) -> None:
    text = to_json(document_with_one_asset(), tmp_path)
    next(tmp_path.iterdir()).write_bytes(b"changed")

    with pytest.raises(IRFormatError, match="fig-1"):
        from_json(text, tmp_path)


def test_a_missing_asset_file_is_reported(tmp_path: Path) -> None:
    text = to_json(document_with_one_asset(), tmp_path)
    next(tmp_path.iterdir()).unlink()

    with pytest.raises(IRFormatError, match="fig-1"):
        from_json(text, tmp_path)


def test_a_block_id_called_type_is_not_mistaken_for_a_tag(tmp_path: Path) -> None:
    doc = Document(
        meta=Meta(title="T"),
        blocks=(Paragraph(id="type", runs=()),),
        provenance={"type": Provenance(adapter="pdf")},
    )

    assert from_json(to_json(doc, tmp_path), tmp_path) == doc


def test_another_ir_version_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(to_json(document_with_one_asset(), tmp_path))
    payload["ir_version"] = 999

    with pytest.raises(IRFormatError, match="999"):
        from_json(json.dumps(payload), tmp_path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "not valid JSON"),
        ("[]", "no 'document'"),
        ('{"ir_version": 1, "document": {"type": "Nope"}}', "unknown type 'Nope'"),
        ('{"ir_version": 1, "document": {"type": "Document"}}', "bad Document"),
        ('{"ir_version": 1, "document": {"type": "Text", "text": "x"}}', "not a Document"),
    ],
)
def test_malformed_files_fail_clearly(text: str, message: str, tmp_path: Path) -> None:
    with pytest.raises(IRFormatError, match=message):
        from_json(text, tmp_path)


def test_the_size_of_a_formula_survives_the_round_trip(tmp_path: Path) -> None:
    asset = Asset(
        id="m",
        mime="image/png",
        bytes=b"x",
        box=MathBox(width=1.25, height=2.5, depth=0.75),
    )
    doc = Document(
        meta=Meta(title="T"),
        blocks=(Paragraph(id="p", runs=(MathInline("", "x", "m"),)),),
        assets={"m": asset},
    )
    assert from_json(to_json(doc, tmp_path), tmp_path) == doc
