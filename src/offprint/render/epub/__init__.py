"""EPUB renderer: write the document IR as a Kindle-friendly reflowable EPUB 3 (#5).

`render_epub` raises `EpubRenderError` for a document it can't render. Anything it could render
but had to change is logged and returned in `EpubResult.problems`, with one of these codes:

| Code | Meaning |
|---|---|
| `epub.invalid_xml_chars` | Characters XHTML can't hold were stripped. |
| `epub.equation_text_fallback` | An equation has no image, so its text is shown instead (#12). |
| `epub.link_dropped` | A link's target can't go in an EPUB, so only its text is kept. |
| `epub.asset_converted` | An image that isn't PNG or JPEG was converted to PNG. |
"""

from offprint.render.epub.renderer import EpubOptions, EpubRenderError, EpubResult, render_epub

__all__ = ["EpubOptions", "EpubRenderError", "EpubResult", "render_epub"]
