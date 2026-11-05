"""Each rule of `validate`, with an example that breaks it and a valid neighbour."""

from dataclasses import replace

from offprint.ir import (
    Asset,
    Block,
    Bold,
    Document,
    Equation,
    Figure,
    Heading,
    MathInline,
    Meta,
    Paragraph,
    Provenance,
    Table,
    Text,
    validate,
)

CELL = (Text("x"),)


def doc_of(*blocks: Block, assets: tuple[Asset, ...] = ()) -> Document:
    return Document(
        meta=Meta(title="T"),
        blocks=blocks,
        assets={asset.id: asset for asset in assets},
        provenance={block.id: Provenance(adapter="test") for block in blocks},
    )


def codes(doc: Document) -> list[str]:
    return [problem.code for problem in validate(doc)]


def figure(block_id: str, number: str, asset: str = "a") -> Figure:
    return Figure(id=block_id, number=number, asset=asset, caption=())


def table(block_id: str, number: str, rows: tuple[tuple[tuple[Text, ...], ...], ...] = ()) -> Table:
    return Table(id=block_id, number=number, caption=(), header=(CELL, CELL), rows=rows)


def heading(block_id: str, level: int) -> Heading:
    return Heading(id=block_id, level=level, runs=())


ASSET = Asset(id="a", mime="image/png", bytes=b"x")


def test_a_well_formed_document_has_no_problems() -> None:
    doc = doc_of(
        heading("h1", 1),
        heading("h2", 2),
        figure("f1", "1"),
        table("t1", "1", rows=((CELL, CELL),)),
        Equation(id="e1", alt="E", latex="E"),
        assets=(ASSET,),
    )

    assert validate(doc) == []


def test_figure_with_a_missing_asset() -> None:
    problems = validate(doc_of(figure("f1", "1")))

    assert [(problem.code, problem.block_id) for problem in problems] == [
        ("asset.unresolved", "f1")
    ]


def test_equation_with_a_missing_asset() -> None:
    assert codes(doc_of(Equation(id="e1", alt="E", asset="gone"))) == ["asset.unresolved"]


def test_asset_stored_under_another_id() -> None:
    doc = Document(meta=Meta(title="T"), assets={"other": ASSET})

    assert codes(doc) == ["asset.id_mismatch"]


def test_duplicate_figure_numbers() -> None:
    doc = doc_of(figure("f1", "1"), figure("f2", "1"), assets=(ASSET,))

    assert codes(doc) == ["figure.duplicate_number"]
    assert validate(doc)[0].block_id == "f2"


def test_duplicate_table_numbers() -> None:
    assert codes(doc_of(table("t1", "1"), table("t2", "1"))) == ["table.duplicate_number"]


def test_a_figure_and_a_table_may_share_a_number() -> None:
    assert validate(doc_of(figure("f1", "1"), table("t1", "1"), assets=(ASSET,))) == []


def test_table_row_wider_than_its_header() -> None:
    assert codes(doc_of(table("t1", "1", rows=((CELL, CELL, CELL),)))) == ["table.width"]


def test_table_row_narrower_than_its_header() -> None:
    assert codes(doc_of(table("t1", "1", rows=((CELL,),)))) == ["table.width"]


def test_heading_jumping_two_levels() -> None:
    assert codes(doc_of(heading("h1", 1), heading("h2", 3))) == ["heading.jump"]


def test_first_heading_must_be_level_one() -> None:
    assert codes(doc_of(heading("h1", 2))) == ["heading.jump"]


def test_heading_may_climb_any_number_of_levels() -> None:
    blocks = heading("a", 1), heading("b", 2), heading("c", 3), heading("d", 1)

    assert validate(doc_of(*blocks)) == []


def test_heading_level_below_one() -> None:
    assert codes(doc_of(heading("h1", 0))) == ["heading.level"]


def test_duplicate_block_ids() -> None:
    doc = doc_of(heading("h1", 1), heading("h1", 1))

    assert codes(doc) == ["block.duplicate_id"]


def test_block_without_provenance() -> None:
    doc = replace(doc_of(heading("h1", 1)), provenance={})

    assert codes(doc) == ["provenance.missing"]


def test_provenance_for_an_unknown_block() -> None:
    doc = replace(doc_of(), provenance={"ghost": Provenance(adapter="test")})

    assert codes(doc) == ["provenance.unknown_block"]


def test_equation_with_neither_latex_nor_asset() -> None:
    assert codes(doc_of(Equation(id="e1", alt="E"))) == ["equation.empty"]


def test_inline_math_with_a_missing_asset() -> None:
    doc = doc_of(Paragraph(id="p", runs=(Bold((MathInline("", "x", "gone"),)),)))
    assert codes(doc) == ["asset.unresolved"]


def test_inline_math_in_the_abstract_with_a_missing_asset() -> None:
    doc = replace(doc_of(), meta=Meta(title="T", abstract=(MathInline("", "x", "gone"),)))
    assert codes(doc) == ["asset.unresolved"]
