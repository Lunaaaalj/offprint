"""Inline math simple enough to be text: `x_i`, `\\alpha`, `n \\le 10`. Pure.

Text reflows, follows the reader's font and stays searchable, so an image is only for what text
can't show. Anything this module doesn't recognise returns None and becomes an image, so it's
written to refuse rather than to guess. The symbols are ones Kindle fonts carry.
"""

import re

from offprint.ir import Italic, Runs, Sub, Sup, Text

_GREEK = {
    name: chr(code)
    for name, code in {
        "alpha": 0x3B1,
        "beta": 0x3B2,
        "gamma": 0x3B3,
        "delta": 0x3B4,
        "epsilon": 0x3B5,
        "varepsilon": 0x3B5,
        "zeta": 0x3B6,
        "eta": 0x3B7,
        "theta": 0x3B8,
        "iota": 0x3B9,
        "kappa": 0x3BA,
        "lambda": 0x3BB,
        "mu": 0x3BC,
        "nu": 0x3BD,
        "xi": 0x3BE,
        "pi": 0x3C0,
        "rho": 0x3C1,
        "sigma": 0x3C3,
        "tau": 0x3C4,
        "upsilon": 0x3C5,
        "phi": 0x3C6,
        "varphi": 0x3C6,
        "chi": 0x3C7,
        "psi": 0x3C8,
        "omega": 0x3C9,
    }.items()
}
# Capital Greek is upright in TeX.
_CAPITALS = {
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
}
_RELATIONS = {
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "neq": "≠",
    "ne": "≠",
    "approx": "≈",
    "times": "×",
    "pm": "±",
    "to": "→",
    "rightarrow": "→",
    "in": "∈",
    "sim": "~",
}
_SYMBOLS = {"infty": "∞", "cdot": "·", "ldots": "…", "dots": "…", "partial": "∂"}
_FUNCTIONS = frozenset(
    {"log", "ln", "exp", "sin", "cos", "tan", "max", "min", "det", "dim", "ker", "deg", "gcd"}
)
_SPACES = frozenset({",", ";", ":", " ", "quad"})
_BINARY = {"=": "=", "+": "+", "-": "−", "<": "<", ">": ">"}
_PUNCTUATION = frozenset("()[],./|!'")

_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|\s+|.", re.DOTALL)


def simple_math(latex: str) -> Runs | None:
    """Return `latex` as runs if it's simple enough, otherwise None."""
    tokens = [token for token in _TOKEN.findall(latex) if not token.isspace()]
    if not tokens:
        return None
    runs = _sequence(tokens, in_script=False)
    return _merge_text(runs) if runs else None


def _atom(token: str) -> Runs | None:
    """One letter, digit or symbol."""
    if token.isascii() and token.isalpha() and len(token) == 1:
        return (Italic((Text(token),)),)
    if token.isascii() and token.isdigit():
        return (Text(token),)
    if token in _PUNCTUATION:
        return (Text(token),)
    if not token.startswith("\\"):
        return None
    name = token[1:]
    if name in _GREEK:
        return (Italic((Text(_GREEK[name]),)),)
    text = _CAPITALS.get(name) or _SYMBOLS.get(name)
    if text is None and name in _FUNCTIONS:
        text = name
    return (Text(text),) if text else None


def _binary(token: str) -> str | None:
    if token in _BINARY:
        return _BINARY[token]
    return _RELATIONS.get(token[1:]) if token.startswith("\\") else None


def _script(tokens: list[str], index: int) -> tuple[Runs, int] | None:
    """Read the argument of `_` or `^` at `index`. Returns its runs and the next index."""
    if index >= len(tokens):
        return None
    if tokens[index] != "{":
        runs = _atom(tokens[index])
        return (runs, index + 1) if runs else None
    if "}" not in tokens[index:]:
        return None
    end = tokens.index("}", index)
    runs = _sequence(tokens[index + 1 : end], in_script=True)
    return (runs, end + 1) if runs else None


def _sequence(tokens: list[str], *, in_script: bool) -> Runs | None:
    runs: Runs = ()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith("\\") and token[1:] in _SPACES:
            continue
        if (symbol := _binary(token)) is not None:
            # A leading sign isn't a binary operator, and a script has no room for spaces.
            spaced = not in_script and bool(runs)
            runs += (Text(f" {symbol} " if spaced else symbol),)
            continue
        atom = _atom(token)
        if atom is None:
            return None
        runs += atom
        if index < len(tokens) and tokens[index] in ("_", "^"):
            if in_script:
                return None
            kind = Sub if tokens[index] == "_" else Sup
            script = _script(tokens, index + 1)
            if script is None:
                return None
            inner, index = script
            # Stacked scripts (x_i^2) would sit side by side in text.
            if index < len(tokens) and tokens[index] in ("_", "^"):
                return None
            runs += (kind(inner),)
    return runs


def _merge_text(runs: Runs) -> Runs:
    merged: list = []
    for run in runs:
        if isinstance(run, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].text + run.text)
        else:
            merged.append(run)
    return tuple(merged)
