# Kindle preview renderer

Labels: enhancement, area:qa
Milestone: M1: Package the prototype
Depends on: #5

A quick visual check: `offprint preview book.epub` renders Kindle-sized pages to PNGs. The QA report links them so a human can look at the pages that matter.

## Scope

- Port `prototype/preview_pages.py` and `prototype/device_frame.py`: Chromium via Playwright, a 412×549 CSS viewport at 3× (Paperwhite 6.8"), pagination with CSS columns, a status bar (time, pages left in chapter, %), optional bezel and grayscale e-ink look.
- Page selection: `--pages chapter:page`, or automatic: the first page, the first page with a figure, with an equation and with a table, plus every page whose blocks a QA check flagged.
- Font: bundle an OFL serif close to Bookerly (Literata), fetched at install or vendored with its license.
- Output: individual PNGs plus a contact sheet.

## Acceptance criteria

- [ ] `offprint preview` on the fixture EPUB produces the automatic selection in < 15 s.
- [ ] Pages flagged by #6 are included and labelled with the check id.

## Out of scope

Pixel-accurate Kindle rendering (it's an approximation, and the docs say so).
