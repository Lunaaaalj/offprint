"""Every check the gate reports, with its stable id, severity and a hint for fixing it.

A check keeps its id for good: `qa.json` readers (#7, #13, #17) rely on them. Checks of the IR
(`offprint.ir.validate`), the renderer (`epub.*`) and the cover (`cover.*`) keep the codes they
have at their source.
"""

from dataclasses import dataclass

from offprint.qa.model import Severity


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    severity: Severity
    hint: str


_IR_HINT = "A bug in the adapter or a cleanup step: the IR breaks a rule of docs/ir.md."

CHECKS: tuple[Check, ...] = (
    Check(
        "coverage.words",
        "error",
        "Text was lost between the source and the book. Look at the listed pages for a block the "
        "adapter dropped or gave the wrong role.",
    ),
    Check(
        "counts.figures",
        "error",
        "A figure caption and the figure blocks disagree. Check the caption pattern in the "
        "profile and the figure's page.",
    ),
    Check(
        "counts.tables",
        "error",
        "A table caption and the table blocks disagree. Check the caption pattern in the profile "
        "and whether table detection found the table.",
    ),
    Check(
        "counts.equations",
        "error",
        "The equation numbers aren't 1..n once each. Check the equation rules in the profile.",
    ),
    Check(
        "table.width",
        "error",
        "A row is wider or narrower than the header. Look for a cell lost or split by detection.",
    ),
    Check(
        "table.empty_header",
        "error",
        "An empty header usually means a phantom column: detection cut a real column in two.",
    ),
    Check(
        "table.ref_rows",
        "error",
        "A first cell has no year at its end: text from another column landed in it, or a wrapped "
        "row wasn't joined.",
    ),
    Check(
        "reference.numbering",
        "error",
        "Numbered references aren't 1..n once each, or an entry has no number. A line that ends in "
        "a full stop may have split its entry: set `references.entry_start` in the profile.",
    ),
    Check(
        "pdf.dropped_text",
        "error",
        "Text that touches a figure or table was left out and isn't inside it: a label of the "
        "figure, or a column the table swallowed. Set `figures.labels` in the profile, or look at "
        "the page.",
    ),
    Check(
        "figure.foreign_caption",
        "error",
        "The figure's box took in another caption. Check how the crop is bounded in the profile.",
    ),
    Check(
        "xhtml.wellformed",
        "error",
        "A reader would drop this file from the book. Look for characters the renderer let "
        "through.",
    ),
    Check(
        "epubcheck",
        "error",
        "The EPUB breaks the spec, and Send to Kindle may refuse it. Run epubcheck on it for "
        "details. Without epubcheck installed this is skipped.",
    ),
    Check(
        "meta.required",
        "error",
        "A book needs a title, an author and a license. Check the metadata rules in the profile, "
        "or run `offprint resolve` so the registry can fill the gap.",
    ),
    Check(
        "meta.author_name",
        "error",
        "An author's name has an email address, a footnote mark or a digit in it: the byline was "
        "split in the wrong place. Check `metadata.author_markers` and `metadata.email` in the "
        "profile.",
    ),
    Check("block.duplicate_id", "error", _IR_HINT),
    Check("provenance.missing", "error", _IR_HINT),
    Check("provenance.unknown_block", "error", _IR_HINT),
    Check("asset.unresolved", "error", _IR_HINT),
    Check("asset.id_mismatch", "error", _IR_HINT),
    Check("figure.duplicate_number", "error", _IR_HINT),
    Check("table.duplicate_number", "error", _IR_HINT),
    Check("equation.empty", "error", _IR_HINT),
    Check("heading.level", "error", _IR_HINT),
    Check("heading.jump", "error", _IR_HINT),
    Check(
        "epub.invalid_xml_chars",
        "warn",
        "The renderer removed them, so the book is safe, but a cleanup step let them through.",
    ),
    Check(
        "epub.equation_text_fallback",
        "warn",
        "This equation reads as plain text in the book, which is hard to read. Look for a "
        "`math.*` finding that says why.",
    ),
    Check(
        "epub.inline_math_text_fallback",
        "warn",
        "This inline formula reads as plain text in the book, which is hard to read.",
    ),
    Check("epub.link_dropped", "warn", "Only the link's text is in the book. Check its target."),
    Check(
        "epub.asset_converted", "warn", "A figure wasn't PNG or JPEG. Check that it still reads."
    ),
    Check(
        "jats.unmapped_element",
        "error",
        "The article has something with no mapping, and a sub-article isn't converted at all. "
        "Check that nothing the reader needs is missing.",
    ),
    Check(
        "jats.figure_without_graphic",
        "error",
        "The source has a figure with no image, so the book only has its caption.",
    ),
    Check("jats.empty_formula", "error", "The source has an equation with nothing in it."),
    Check("jats.unmapped_inline", "warn", "An inline element has no mapping. Its text is kept."),
    Check(
        "jats.math_fallback",
        "warn",
        "Part of an equation couldn't become LaTeX, so it reads as plain text.",
    ),
    Check(
        "jats.inline_graphic",
        "warn",
        "The IR has no inline images, so alt text or `[image]` stands in for this one.",
    ),
    Check(
        "jats.table_as_figure",
        "warn",
        "This table is only an image in the source, so the reader can't reflow it.",
    ),
    Check(
        "jats.license_unknown",
        "warn",
        "The license has no Creative Commons URL, so it was left out rather than guessed.",
    ),
    Check(
        "jats.no_front",
        "warn",
        "The article has no `article-meta`. Run `offprint resolve` so the registry can fill the "
        "metadata.",
    ),
    Check(
        "math.renderer_unavailable",
        "error",
        "Chromium couldn't start, so no LaTeX was typeset and every such equation is plain text. "
        "Run `uv run playwright install chromium`.",
    ),
    Check(
        "math.preamble_failed",
        "error",
        "The paper's macros didn't load, so formulas that use them may be wrong. Check the "
        "preamble the adapter passed.",
    ),
    Check(
        "math.render_failed",
        "warn",
        "MathJax rejected this LaTeX, so the equation stays as text. Check the source's LaTeX.",
    ),
    Check(
        "math.system_font",
        "warn",
        "A symbol isn't in MathJax's fonts, so it was drawn from a system font and may differ "
        "between machines.",
    ),
    Check(
        "math.cache_unwritable",
        "warn",
        "Rendered equations weren't cached, so the next conversion repeats the work. Check "
        "OFFPRINT_CACHE_DIR.",
    ),
    Check("cover.overflow", "error", "Text left the cover, so the conversion stopped."),
    Check("cover.contrast", "error", "Text on the cover is too faint, so the conversion stopped."),
)

BY_ID = {check.id: check for check in CHECKS}
