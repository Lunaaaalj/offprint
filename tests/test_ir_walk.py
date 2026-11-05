"""`map_runs` and friends reach every run in every block."""

from offprint.ir import (
    Bold,
    Equation,
    Figure,
    Heading,
    Italic,
    Link,
    ListItem,
    MathInline,
    Paragraph,
    Reference,
    Table,
    Text,
    iter_runs,
    map_block_runs,
    map_runs,
)


def shout(run):
    return (Text(run.text.upper()), Text("!")) if isinstance(run, Text) else (run,)


def test_map_runs_keeps_the_containers() -> None:
    runs = (Text("a"), Italic((Bold((Text("b"),)),)), Link("u", (Text("c"),)), MathInline("x"))
    assert map_runs(runs, shout) == (
        Text("A"),
        Text("!"),
        Italic((Bold((Text("B"), Text("!"))),)),
        Link("u", (Text("C"), Text("!"))),
        MathInline("x"),
    )


def test_every_block_with_runs_is_reached() -> None:
    a = (Text("a"),)
    blocks = [
        Heading(id="h", level=1, runs=a),
        Paragraph(id="p", runs=a),
        ListItem(id="l", runs=a),
        Reference(id="r", runs=a),
        Figure(id="f", number="1", asset="x", caption=a),
    ]
    assert [[run.text for run in iter_runs(block)] for block in blocks] == [["a"]] * 5


def test_every_part_of_a_table_is_reached() -> None:
    table = Table(
        id="t",
        number="1",
        caption=(Text("c"),),
        header=(((Text("h"),)),),
        rows=(((Text("r"),),),),
        notes=(Text("n"),),
    )
    assert [run.text for run in iter_runs(table)] == ["c", "h", "r", "n"]
    assert map_block_runs(table, shout).rows == (((Text("R"), Text("!")),),)


def test_an_equation_holds_no_runs() -> None:
    equation = Equation(id="e", alt="a", latex="a")
    assert list(iter_runs(equation)) == []
    assert map_block_runs(equation, shout) == equation
