"""MathML to LaTeX, for `Equation.latex`, and to one line of text, for `alt`. Pure.

Covers presentation MathML. Anything else raises `UnsupportedMathML`, so the caller can report the
equation instead of writing LaTeX that quietly lost part of it.
"""

import re
from collections.abc import Iterable

from offprint.adapters.jats.xml import Element, children, collapse, local, text_of

_TEX_ENCODINGS = frozenset({"application/x-tex", "tex", "latex"})
_FUNCTIONS = frozenset(
    "arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom inf ker lg lim liminf "
    "limsup ln log max min Pr sec sin sinh sup tan tanh".split()
)
_LIMIT_OPERATORS = frozenset(
    r"\sum \prod \coprod \int \oint \bigcup \bigcap \lim \max \min \sup \inf".split()
)
_OVER_ACCENTS = {
    "^": r"\hat",
    "ˆ": r"\hat",
    "∧": r"\hat",
    "~": r"\tilde",
    "˜": r"\tilde",
    "→": r"\vec",
    "⃗": r"\vec",
    ".": r"\dot",
    "˙": r"\dot",
    "¨": r"\ddot",
    "¯": r"\overline",
    "‾": r"\overline",
    "―": r"\overline",
    "_": r"\overline",
}
_UNDER_ACCENTS = {"_": r"\underline", "̲": r"\underline", "¯": r"\underline", "‾": r"\underline"}
_VARIANTS = {
    "normal": r"\mathrm",
    "bold": r"\mathbf",
    "bold-italic": r"\boldsymbol",
    "double-struck": r"\mathbb",
    "script": r"\mathcal",
    "fraktur": r"\mathfrak",
}
_GREEK = (
    "alpha beta gamma delta varepsilon zeta eta theta iota kappa lambda mu nu xi o pi rho "
    "varsigma sigma tau upsilon varphi chi psi omega"
)
_SYMBOLS = {
    **{chr(0x3B1 + index): f"\\{name}" for index, name in enumerate(_GREEK.split())},
    "ο": "o",
    "ϵ": r"\epsilon",
    "ϑ": r"\vartheta",
    "ϕ": r"\phi",
    "ϱ": r"\varrho",
    "ϖ": r"\varpi",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Υ": r"\Upsilon",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
    # Operators and relations
    "∑": r"\sum",
    "∏": r"\prod",
    "∐": r"\coprod",
    "∫": r"\int",
    "∮": r"\oint",
    "⋃": r"\bigcup",
    "⋂": r"\bigcap",
    "−": "-",
    "–": "-",
    "∗": "*",
    "×": r"\times",
    "·": r"\cdot",
    "⋅": r"\cdot",
    "∙": r"\cdot",
    "÷": r"\div",
    "±": r"\pm",
    "∓": r"\mp",
    "≤": r"\leq",
    "⩽": r"\leq",
    "≥": r"\geq",
    "⩾": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "≃": r"\simeq",
    "≅": r"\cong",
    "≡": r"\equiv",
    "∼": r"\sim",
    "∝": r"\propto",
    "≪": r"\ll",
    "≫": r"\gg",
    "∈": r"\in",
    "∉": r"\notin",
    "∋": r"\ni",
    "⊂": r"\subset",
    "⊃": r"\supset",
    "⊆": r"\subseteq",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\emptyset",
    "∀": r"\forall",
    "∃": r"\exists",
    "¬": r"\neg",
    "∧": r"\wedge",
    "∨": r"\vee",
    "⊕": r"\oplus",
    "⊗": r"\otimes",
    "∘": r"\circ",
    "†": r"\dagger",
    "∂": r"\partial",
    "∇": r"\nabla",
    "∞": r"\infty",
    "ℓ": r"\ell",
    "ℏ": r"\hbar",
    "ℝ": r"\mathbb{R}",
    "ℕ": r"\mathbb{N}",
    "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}",
    "ℂ": r"\mathbb{C}",
    "′": "'",
    "″": "''",
    "°": r"^{\circ}",
    "…": r"\ldots",
    "⋯": r"\cdots",
    "⋮": r"\vdots",
    "⋱": r"\ddots",
    # Arrows and fences
    "→": r"\rightarrow",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "⇐": r"\Leftarrow",
    "⇔": r"\Leftrightarrow",
    "↦": r"\mapsto",
    "⟨": r"\langle",
    "〈": r"\langle",
    "⟩": r"\rangle",
    "〉": r"\rangle",
    "⌊": r"\lfloor",
    "⌋": r"\rfloor",
    "⌈": r"\lceil",
    "⌉": r"\rceil",
    "‖": r"\|",
    "∣": "|",
    # Characters LaTeX reserves
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "#": r"\#",
    "$": r"\$",
    "&": r"\&",
    "_": r"\_",
    "~": r"\sim",
    "^": r"\wedge",
    "\\": r"\backslash",
    # Spaces, visible and invisible
    " ": "~",
    " ": r"\;",
    " ": r"\quad",
    " ": r"\,",
    " ": r"\,",
    " ": r"\:",
    "​": "",
    "⁡": "",
    "⁢": "",
    "⁣": "",
    "⁤": "",
}
_TEXT_SPACES = str.maketrans(dict.fromkeys("      ", " "))
_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}
_ATOM = re.compile(r"[A-Za-z0-9]|\\[A-Za-z]+|\\text\{[^{}]*\}")
_ENDS_IN_COMMAND = re.compile(r"\\[A-Za-z]+$")


class UnsupportedMathML(ValueError):
    """The MathML holds something this converter can't express in LaTeX."""


def mathml_to_latex(math: Element) -> str:
    """Convert `<math>` or any part of it. Raises `UnsupportedMathML`."""
    return _tex(math)


def tex_text(text: str) -> str:
    """Return plain text as LaTeX, for maths that can only be shown as words."""
    plain = collapse(text.translate(_TEXT_SPACES))
    return r"\text{" + "".join(_TEXT_ESCAPES.get(char, char) for char in plain) + "}"


def mathml_to_text(math: Element) -> str:
    """One line of readable text: `x_i`, `x^2`, `(a)/(b)`, `√(x)`."""
    return collapse(_plain(math))


def _join(parts: Iterable[str]) -> str:
    return " ".join(part for part in parts if part)


def _tex(element: Element) -> str:
    name = local(element)
    kids = list(children(element))
    match name:
        case "math" | "mrow" | "mstyle" | "mpadded" | "menclose" | "mtd":
            return _join(_tex(kid) for kid in kids)
        case "mi":
            return _identifier(element)
        case "mn":
            return _characters(element.text or "")
        case "mo":
            return _operator(element)
        case "mtext" | "ms":
            text = (element.text or "").translate(_TEXT_SPACES)
            return tex_text(text) if text.strip() else r"\ "
        case "mspace":
            return r"\,"
        case "mphantom" | "none":
            return ""
        case "mfenced":
            return _fenced(element, kids)
        case "mfrac":
            top, bottom = _arguments(name, kids, 2)
            if element.get("linethickness") in ("0", "0pt", "0px"):
                return rf"\genfrac{{}}{{}}{{0pt}}{{}}{{{top}}}{{{bottom}}}"
            return rf"\frac{{{top}}}{{{bottom}}}"
        case "msqrt":
            return rf"\sqrt{{{_join(_tex(kid) for kid in kids)}}}"
        case "mroot":
            body, degree = _arguments(name, kids, 2)
            return rf"\sqrt[{degree}]{{{body}}}"
        case "msub":
            base, sub = _arguments(name, kids, 2)
            return f"{_base(base)}_{{{sub}}}"
        case "msup":
            base, power = _arguments(name, kids, 2)
            return f"{_base(base)}^{{{power}}}"
        case "msubsup":
            base, sub, power = _arguments(name, kids, 3)
            return f"{_base(base)}_{{{sub}}}^{{{power}}}"
        case "munder":
            return _under(name, kids)
        case "mover":
            return _over(name, kids)
        case "munderover":
            base, under, over = _arguments(name, kids, 3)
            if base in _LIMIT_OPERATORS:
                return f"{base}_{{{under}}}^{{{over}}}"
            return rf"\overset{{{over}}}{{\underset{{{under}}}{{{base}}}}}"
        case "mtable":
            return _table(element, kids)
        case "semantics":
            return _semantics(kids)
        case "maction" if kids:
            return _tex(kids[0])
    raise UnsupportedMathML(f"<{name}> has no LaTeX mapping")


def _arguments(name: str, kids: list[Element], count: int) -> list[str]:
    if len(kids) != count:
        raise UnsupportedMathML(f"<{name}> needs {count} children, found {len(kids)}")
    return [_tex(kid) for kid in kids]


def _base(tex: str) -> str:
    """Brace a sub- or superscript's base, unless it's one token."""
    return tex if _ATOM.fullmatch(tex) else f"{{{tex}}}"


def _characters(text: str) -> str:
    tex = ""
    for char in collapse(text):
        if char not in _SYMBOLS and not char.isascii():
            raise UnsupportedMathML(f"no LaTeX for {char!r} (U+{ord(char):04X})")
        token = _SYMBOLS.get(char, char)
        # A command must not swallow the letter after it.
        tex += " " + token if _ENDS_IN_COMMAND.search(tex) and token[:1].isalpha() else token
    return tex


def _identifier(element: Element) -> str:
    text = collapse(element.text or "")
    if len(text) > 1 and text in _FUNCTIONS:
        return f"\\{text}"
    variant = element.get("mathvariant") or ("normal" if len(text) > 1 else None)
    if variant in _VARIANTS:
        return f"{_VARIANTS[variant]}{{{_characters(text)}}}"
    return _characters(text)


def _operator(element: Element) -> str:
    text = collapse(element.text or "")
    if text in _FUNCTIONS:
        return f"\\{text}"
    if len(text) > 1 and text.isascii() and text.isalpha():
        return rf"\mathrm{{{text}}}"
    return _characters(text)


def _fenced(element: Element, kids: list[Element]) -> str:
    separator = (element.get("separators", ",").strip() or " ")[0]
    middle = f" {_characters(separator)} ".join(_tex(kid) for kid in kids)
    return _join(
        (_characters(element.get("open", "(")), middle, _characters(element.get("close", ")")))
    )


def _under(name: str, kids: list[Element]) -> str:
    if len(kids) == 2 and (accent := _UNDER_ACCENTS.get(text_of(kids[1]))):
        return f"{accent}{{{_tex(kids[0])}}}"
    base, under = _arguments(name, kids, 2)
    if base in _LIMIT_OPERATORS:
        return f"{base}_{{{under}}}"
    return rf"\underset{{{under}}}{{{base}}}"


def _over(name: str, kids: list[Element]) -> str:
    if len(kids) == 2 and (accent := _OVER_ACCENTS.get(text_of(kids[1]))):
        return f"{accent}{{{_tex(kids[0])}}}"
    base, over = _arguments(name, kids, 2)
    if base in _LIMIT_OPERATORS:
        return f"{base}^{{{over}}}"
    return rf"\overset{{{over}}}{{{base}}}"


def _table(element: Element, kids: list[Element]) -> str:
    rows = [_row(row) for row in kids]
    if len(rows) == 1 and len(rows[0]) == 1:
        return rows[0][0]
    alignment = (element.get("columnalign") or "center").split()[0][0]
    columns = (alignment if alignment in "lcr" else "c") * max(map(len, rows), default=1)
    lines = r" \\ ".join(" & ".join(row) for row in rows)
    return rf"\begin{{array}}{{{columns}}} {lines} \end{{array}}"


def _row(row: Element) -> list[str]:
    cells = list(children(row))
    if local(row) == "mlabeledtr":  # The first cell is the equation number, which has a <label>.
        cells = cells[1:]
    elif local(row) != "mtr":
        raise UnsupportedMathML(f"<{local(row)}> isn't a table row")
    return [_tex(cell) for cell in cells]


def _semantics(kids: list[Element]) -> str:
    for kid in kids:
        encoding = (kid.get("encoding") or "").lower()
        if local(kid) == "annotation" and encoding in _TEX_ENCODINGS and kid.text:
            return collapse(kid.text)
    if not kids:
        raise UnsupportedMathML("<semantics> is empty")
    return _tex(kids[0])


def _plain(element: Element) -> str:
    name = local(element)
    kids = [_plain(kid) for kid in children(element)]
    match name:
        case "msub" | "munder" if len(kids) == 2:
            return f"{kids[0]}_{kids[1]}"
        case "mover" if len(kids) == 2:
            return (
                f"{kids[0]}{kids[1]}"
                if text_of(element[1]) in _OVER_ACCENTS
                else f"{kids[0]}^{kids[1]}"
            )
        case "msup" if len(kids) == 2:
            return f"{kids[0]}^{kids[1]}"
        case "msubsup" | "munderover" if len(kids) == 3:
            return f"{kids[0]}_{kids[1]}^{kids[2]}"
        case "mfrac" if len(kids) == 2:
            return f"({kids[0]})/({kids[1]})"
        case "msqrt":
            return f"√({''.join(kids)})"
        case "mphantom" | "annotation" | "annotation-xml":
            return ""
        case "mtr" | "mlabeledtr":
            return " ".join(kids) + " "
    return (element.text or "") + "".join(kids)
