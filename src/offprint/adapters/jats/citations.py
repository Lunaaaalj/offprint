"""`<ref>` to the runs of a `Reference`. Pure, apart from the list of problems."""

from offprint.adapters.jats.inline import child_runs, content_runs, inline_runs, tidy_runs
from offprint.adapters.jats.xml import Element, children, local, text_of
from offprint.ir import Italic, Problem, Run, Runs, Text

_CITATIONS = ("mixed-citation", "element-citation", "citation", "nlm-citation")
_AUTHORS = ("person-group", "collab", "name", "string-name")
_TITLES = ("article-title", "chapter-title", "data-title", "part-title")


def reference_doi(ref: Element) -> str | None:
    found = ref.find(".//pub-id[@pub-id-type='doi']")
    return text_of(found) or None


def reference_runs(ref: Element, problems: list[Problem]) -> Runs:
    """A reference's text. Mixed citations hold their punctuation, element citations don't."""
    runs: list[Run] = []
    label = text_of(ref.find("label"))
    if label:
        runs.append(Text(f"{label} "))
    citation = next(ref.iter(*_CITATIONS), None)
    if citation is None:
        return tidy_runs((*runs, *content_runs(ref, problems)))
    if local(citation) == "element-citation":
        return tidy_runs((*runs, *_structured(citation, problems)))
    return tidy_runs((*runs, *_mixed(citation, problems)))


def _mixed(citation: Element, problems: list[Problem]) -> Runs:
    runs: list[Run] = [Text(citation.text)] if citation.text else []
    for child in children(citation):
        runs.extend(_mixed_child(child, problems))
        if child.tail:
            runs.append(Text(child.tail))
    return tuple(runs)


def _mixed_child(child: Element, problems: list[Problem]) -> Runs:
    match local(child):
        case "person-group":
            return (Text(_person_group(child)),)
        case "name":
            return (Text(_cited_name(child)),)
        case "source":
            return (Italic(content_runs(child, problems)),)
        case "pub-id":
            # A DOI has "doi:" before it in the text. PMC appends the other ids bare.
            return (Text(text_of(child)),) if child.get("pub-id-type") == "doi" else ()
    return child_runs(child, problems)


def _person_group(group: Element) -> str:
    """The people in a group, comma-separated: publishers leave that to their style sheet."""
    parts = [group.text or ""]
    for child in children(group):
        if local(child) == "name":
            parts.append(_cited_name(child))
        elif local(child) == "etal":
            parts.append("et al.")
        else:
            parts.append(text_of(child))
        parts.append(child.tail or "")
    return ", ".join(part.strip() for part in parts if part.strip())


def _cited_name(name: Element) -> str:
    """A `<name>` as bibliographies write it: `Nibila, Y.`."""
    surname, given = text_of(name.find("surname")), text_of(name.find("given-names"))
    return ", ".join(part for part in (surname, given) if part)


def _structured(citation: Element, problems: list[Problem]) -> Runs:
    """Compose a reference from an `<element-citation>`, which holds fields and no punctuation."""
    authors = [_author_text(child) for child in children(citation) if local(child) in _AUTHORS]
    year = text_of(citation.find("year"))
    titles = (citation.find(tag) for tag in _TITLES)
    title = next((found for found in titles if found is not None), None)
    source = citation.find("source")
    runs: list[Run] = []
    if authors:
        runs.append(Text(", ".join(authors) + " "))
    if year:
        runs.append(Text(f"({year}). "))
    if title is not None:
        runs.extend((*inline_runs(title, problems), Text(". ")))
    if source is not None:
        runs.extend((Italic(inline_runs(source, problems)), Text(" ")))
    locator = _locator(citation)
    if locator:
        runs.append(Text(f"{locator}. "))
    return tuple(runs)


def _author_text(child: Element) -> str:
    name = local(child)
    if name == "person-group":
        return _person_group(child)
    return _cited_name(child) if name == "name" else text_of(child)


def _locator(citation: Element) -> str:
    volume = text_of(citation.find("volume"))
    issue = text_of(citation.find("issue"))
    first = text_of(citation.find("fpage")) or text_of(citation.find("elocation-id"))
    pages = "–".join(part for part in (first, text_of(citation.find("lpage"))) if part)
    held = f"{volume}({issue})" if issue else volume
    return ", ".join(part for part in (held, pages) if part)
