# EPUB 3 renderer from the IR

Labels: enhancement, area:render
Milestone: M1: Package the prototype
Depends on: #2

Write a Kindle-friendly EPUB 3 directly from the IR. The prototype went through pandoc's HTML reader, which drops `class` on `<p>` (we had to wrap paragraphs in divs). Writing the package ourselves gives full control and removes the pandoc dependency.

## Scope

- XHTML chapter per top-level heading. Front matter (title, authors, affiliation, abstract, keywords, citation and license) is the first chapter.
- `nav.xhtml` TOC two levels deep. OPF with full metadata (title, creators, date, publisher, identifier = DOI or arXiv id, `dc:rights`, language).
- Cover support: `cover-image` property plus a cover XHTML page (input: PNG from #8).
- Port and tidy `prototype/kindle.css`: serif body, no hyphenation in headings, hanging-indent references, `table-layout: fixed` with word wrapping, centred equation images with LaTeX/text `alt`, figure captions.
- Assets: figures as PNG/JPEG (colour kept), equations grayscale. Optional downscaling to a maximum width (default 1600 px) to keep the file small.
- Every chapter must be well-formed XHTML. Escape everything, strip invalid XML characters as a final safety net, and log when it does so.

## Acceptance criteria

- [ ] The fixture IR renders to an EPUB that passes `epubcheck` with no errors.
- [ ] The TOC lists the 15 top-level sections and their subsections.
- [ ] Opening the EPUB in Calibre's viewer or Apple Books shows figures, tables and equations in place (manual check, screenshots in the PR).
- [ ] No pandoc dependency.

## Out of scope

KFX/AZW3 output (Send to Kindle converts EPUB itself). Other renderers (Markdown, Obsidian).
