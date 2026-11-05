"""Inline content to IR runs, and formulas to LaTeX. Pure, apart from the list of problems."""

import re
from dataclasses import dataclass, replace
from urllib.parse import quote

from offprint.adapters.jats.mathml import (
    UnsupportedMathML,
    mathml_to_latex,
    mathml_to_text,
    tex_text,
)
from offprint.adapters.jats.xml import (
    MATHML_MATH,
    XLINK_HREF,
    Element,
    children,
    local,
    text_of,
)
from offprint.ir import (
    Bold,
    Cite,
    Italic,
    Link,
    MathInline,
    Problem,
    Run,
    Runs,
    Sub,
    Sup,
    Text,
)

_WRAPPERS = {"italic": Italic, "bold": Bold, "sup": Sup, "sub": Sub}
# Elements that only style or label their content, which the IR has no use for.
_TRANSPARENT = frozenset(
    """abbrev addr-line article-title chapter-title chem-struct city collab comment country
    data-title date date-in-citation day edition elocation-id email-group etal fpage given-names
    inline-supplementary-material institution issn issue italic lpage milestone-end milestone-start
    monospace month named-content overline part-title patent person-group phone postal-code
    prefix publisher-loc publisher-name related-article related-object roman sans-serif sc season
    series size source state strike string-date string-name styled-content suffix surname
    trans-source trans-title underline uri-group volume x year""".split()
)
# Elements that break a line, so words on either side must not run together.
_SPACED = frozenset(
    {"p", "title", "label", "break", "list", "list-item", "def", "def-item", "term"}
)
# Metadata about the element around it, never part of the text.
_DROPPED = frozenset({"alt-text", "long-desc", "object-id", "target", "permissions", "attrib-id"})
_DOCUMENT = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.DOTALL)
_DELIMITERS = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$"))
_URL_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_SPACES = re.compile(r"[ \t\r\n]+")


@dataclass(frozen=True, slots=True)
class Formula:
    """What a formula element holds. `latex` is `None` if it holds no maths, only text or images."""

    latex: str | None
    text: str


def inline_runs(element: Element, problems: list[Problem]) -> Runs:
    """The content of `element` as tidy runs."""
    return tidy_runs(content_runs(element, problems))


def content_runs(element: Element, problems: list[Problem]) -> Runs:
    """The content of `element` as raw runs, whitespace included."""
    runs: list[Run] = [Text(element.text)] if element.text else []
    for child in children(element):
        runs.extend(child_runs(child, problems))
        if child.tail:
            runs.append(Text(child.tail))
    return tuple(runs)


def child_runs(child: Element, problems: list[Problem]) -> Runs:
    """One inline element as runs. Unknown elements keep their text and are reported."""
    name = local(child)
    if name in _WRAPPERS:
        inner = content_runs(child, problems)
        return (_WRAPPERS[name](inner),) if inner else ()
    if name in _TRANSPARENT:
        return content_runs(child, problems)
    if name in _SPACED:
        return (Text(" "), *content_runs(child, problems), Text(" "))
    match name:
        case "xref":
            return _xref(child, problems)
        case "ext-link" | "uri" | "email":
            return _link(child, problems)
        case "name":
            return (Text(person_name(child)),)
        case "inline-formula" | "tex-math" | "math" | "alternatives":
            return _inline_formula(child, problems)
        case "inline-graphic" | "graphic":
            return _inline_graphic(child, problems)
    if name in _DROPPED:
        return ()
    message = f"<{name}> has no inline mapping, so only its text was kept"
    problems.append(Problem("jats.unmapped_inline", message))
    return content_runs(child, problems)


def person_name(name: Element) -> str:
    """A `<name>` in reading order: `Y. Nibila`."""
    given = text_of(name.find("given-names"))
    return " ".join(part for part in (given, text_of(name.find("surname"))) if part)


def _xref(element: Element, problems: list[Problem]) -> Runs:
    inner = content_runs(element, problems)
    # `rid` can list several targets. A link can only go to one.
    targets = (element.get("rid") or "").split()
    if not inner or not targets:
        return inner
    return (Cite(targets[0], inner),)


def _link(element: Element, problems: list[Problem]) -> Runs:
    inner = content_runs(element, problems)
    label = text_of(element)
    target = element.get(XLINK_HREF) or label
    if local(element) == "email":
        target = target if target.startswith("mailto:") else f"mailto:{target}"
    elif element.get("ext-link-type") == "doi" and not _URL_SCHEME.match(target):
        target = "https://doi.org/" + quote(target, safe="/:;()._-")
    if not inner:
        inner = (Text(target),)
    return (Link(target, inner),) if _URL_SCHEME.match(target) else inner


def _inline_formula(element: Element, problems: list[Problem]) -> Runs:
    formula = read_formula(element, problems)
    if formula.latex is not None:
        return (MathInline(formula.text, formula.latex),)
    graphic = next(element.iter("inline-graphic", "graphic"), None)
    if graphic is not None:
        return _inline_graphic(graphic, problems)
    return (Text(text_of(element)),) if text_of(element) else ()


def _inline_graphic(element: Element, problems: list[Problem]) -> Runs:
    described = text_of(element.find("alt-text"))
    href = element.get(XLINK_HREF) or "an inline image"
    if described:
        message = f"{href} is shown as its alt text: the IR has no inline images"
        problems.append(Problem("jats.inline_graphic", message))
        return (Text(described),)
    message = f"{href} was dropped: the IR has no inline images, and it has no alt text"
    problems.append(Problem("jats.inline_graphic", message))
    return (Text("[image]"),)


def read_formula(element: Element, problems: list[Problem]) -> Formula:
    """Find the maths in a formula element. TeX wins, because MathML has to be converted."""
    tex = next(element.iter("tex-math"), None)
    math = next(element.iter(MATHML_MATH), None)
    text = mathml_to_text(math) if math is not None else ""
    if tex is not None and text_of(tex):
        latex = tex_source(text_of(tex))
        return Formula(latex, text or latex)
    if math is None:
        return Formula(None, text_of(element, "label"))
    try:
        return Formula(mathml_to_latex(math), text)
    except UnsupportedMathML as error:
        message = f"MathML shown as text, {error}: {text}"
        problems.append(Problem("jats.math_fallback", message))
        return Formula(tex_text(text), text)


def tex_source(tex: str) -> str:
    r"""Reduce `<tex-math>` to the formula: PMC wraps many in a whole `\documentclass` document."""
    found = _DOCUMENT.search(tex)
    body = (found.group(1) if found else tex).strip()
    for opening, closing in _DELIMITERS:
        if body.startswith(opening) and body.endswith(closing) and len(body) > 2 * len(closing) - 1:
            return body[len(opening) : -len(closing)].strip()
    return body


def tidy_runs(runs: Runs) -> Runs:
    """Collapse whitespace across runs, trim the ends, join neighbours and drop what's empty."""
    tidy, _ = _collapse(runs, after_space=True)
    return _merge(_trim_end(tidy))


def _collapse(runs: Runs, after_space: bool) -> tuple[Runs, bool]:
    """Collapse whitespace, carrying over whether the text so far ended in a space."""
    result: list[Run] = []
    for run in runs:
        if isinstance(run, Text):
            text = _SPACES.sub(" ", run.text)
            if after_space:
                text = text.removeprefix(" ")
            if text:
                result.append(Text(text))
                after_space = text.endswith(" ")
        elif isinstance(run, MathInline):
            result.append(run)
            after_space = False
        else:
            inner, after_space = _collapse(run.runs, after_space)
            if inner:
                result.append(replace(run, runs=inner))
    return tuple(result), after_space


def _trim_end(runs: Runs) -> Runs:
    if not runs:
        return runs
    last = runs[-1]
    if isinstance(last, Text):
        text = last.text.rstrip(" ")
        return runs[:-1] + ((Text(text),) if text else ())
    if isinstance(last, MathInline):
        return runs
    inner = _trim_end(last.runs)
    if not inner:
        return _trim_end(runs[:-1])
    return runs[:-1] + (replace(last, runs=inner),)


def _merge(runs: Runs) -> Runs:
    merged: list[Run] = []
    for run in runs:
        if isinstance(run, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].text + run.text)
        elif isinstance(run, Text | MathInline):
            merged.append(run)
        else:
            merged.append(replace(run, runs=_merge(run.runs)))
    return tuple(merged)


def collapse_label(element: Element | None) -> str:
    """A `<label>`'s text without the punctuation around it: `(1)` and `1.` both give `1`."""
    return text_of(element).strip("().:")
