"""Decide what a block is, from the profile's font table."""

import re

from offprint.cleanup import clean_text
from offprint.extraction import Span, TextBlock
from offprint.profiles.schema import Context, Profile, Role, RoleRule


def _pages_match(rule: RoleRule, page: int) -> bool:
    if rule.pages == "first":
        return page == 1
    if rule.pages == "later":
        return page > 1
    return True


def _rule_matches(rule: RoleRule, span: Span, page: int, text: str) -> bool:
    if rule.fonts and not span.font.startswith(tuple(rule.fonts)):
        return False
    if rule.size is not None and not rule.size[0] <= span.size < rule.size[1]:
        return False
    if rule.text is not None and re.search(rule.text, text) is None:
        return False
    return _pages_match(rule, page)


def classify(
    span: Span, profile: Profile, *, page: int, text: str = "", context: Context = "page"
) -> Role | None:
    """Return the role of the first rule of `context` that matches, or None."""
    for rule in profile.roles:
        if rule.context == context and _rule_matches(rule, span, page, text):
            return rule.role
    return None


def first_span(block: TextBlock) -> Span | None:
    """Return the first span with text in it."""
    spans = (span for line in block.lines for span in line.spans if span.text.strip())
    return next(spans, None)


def block_text(block: TextBlock) -> str:
    joined = " ".join("".join(span.text for span in line.spans) for line in block.lines)
    return clean_text(joined).strip()


def block_role(block: TextBlock, profile: Profile, context: Context = "page") -> Role | None:
    span = first_span(block)
    if span is None:
        return None
    return classify(span, profile, page=block.page, text=block_text(block), context=context)
