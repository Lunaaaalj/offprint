# prototype/

These are the throwaway scripts that made the first offprint EPUB, from the fixture in `tests/fixtures/frontiers-frai-2026-1748985/`.
They're kept as a **reference implementation and a record of what went wrong**. Don't build on them.
The milestone 1 issues port each idea into the package and split the publisher-specific parts from the generic ones.

| File | What it does |
|---|---|
| `convert.py` | PDF → `book.html` + `img/`. It uses PyMuPDF for text spans, tables, figure crops and equation crops, and orders blocks for two columns. |
| `build.sh` | `convert.py` → heading shift → pandoc → `book.epub`, then checks each chapter is well-formed XHTML. |
| `kindle.css` | Stylesheet for the EPUB (serif body, hanging-indent references, fixed-layout tables). |
| `preview_pages.py` | Renders Kindle-sized (1236×1648) page screenshots of a chapter with Chromium, using CSS columns to paginate. |
| `device_frame.py` | Puts those screenshots in a Kindle-style bezel, in grayscale. |
| `cover.py` | 1600×2560 cover: a duotone hero image, a network motif and the title, rendered with Chromium. |

Reproduce the fixture EPUB:

```sh
pip install pymupdf playwright numpy pillow && playwright install chromium   # pandoc must be on PATH
OUT=build prototype/build.sh tests/fixtures/frontiers-frai-2026-1748985/paper.pdf
```

## What the fixture taught us

Each item here is a real failure from building the first EPUB. Each one should become a cleanup step with a unit test, or a QA check, or both.
Page numbers are 1-based pages of the fixture PDF.

### Text extraction

1. **Hidden ActualText overlays (p. 3, 8, 10, 12, 18…).** The charts carry alt-text that replaces the visible glyphs in plain extraction. "FIGURE 1" came out as a paragraph of alt-text, and the axis labels came out as prose.
   Fix: extract with `TEXT_IGNORE_ACTUALTEXT`. Keep the alt-text separately, because it's useful as the figure's `alt`.
2. **Ligatures and control characters.** `ﬁ ﬂ ﬀ ﬃ ﬄ` need expanding, and `¸S` should become `Ş`. One stray control character made an entire chapter invalid XHTML, so the EPUB silently lost a chapter.
3. **Spaced-out justified text.** Spans contain runs of spaces, so whitespace has to be collapsed.
4. **Dehyphenation.** Join a trailing `-` with the next line only when the next fragment starts lowercase. This still wrongly merged one real compound ("magnetization-prepared" → "magnetizationprepared"). A dictionary or frequency check would fix that.

### Layout and reading order

5. **Two columns plus full-width items.** Split the page into horizontal bands at each full-width element (title, wide figure, wide table). Inside each band read the left column, then the right.
6. **Paragraphs that continue across columns and pages.** Merge with the previous paragraph when it has no closing punctuation and the next block starts lowercase (or is body-size text). Figures and tables that interrupt a sentence are moved after the merged paragraph. Equations are never merged across.
7. **Running header and footer** at y < 50 and y > 795 pt are dropped. Page 1 has a metadata sidebar at x < 200 pt. Most of it is dropped, but CITATION and COPYRIGHT are kept for the license credit.

### Captions and figures

8. **Captions split into several blocks (Fig. 16 p. 18, Fig. 22 p. 25).** "FIGU" + "RE 16" + "Grap" + "hical…" came out as separate blocks, sometimes in the wrong order inside one block.
   Fix: merge caption blocks that touch, then regroup their spans into lines by y-centre and sort each line by x.
9. **Captions sit *below* the figure** in this template. The figure's region is from the bottom of the nearest body block *or caption* above it down to the caption. Ignoring captions above made Fig. 2 include Fig. 1, Fig. 5 include Fig. 4, and so on.
   Width: full page if any vector or raster element crosses the middle gap, otherwise the caption's column. The crop is the union of drawing and image rectangles in that region.

### Tables

10. **Table detection swallowed the next text column (Table 8, p. 13).** `find_tables()` returned a full-width box with the right-hand body column as a third table column, and the body text vanished.
    Fix: if a detected table covers body text (≥ 3 lines of 9 pt text), keep only the cells on the side without it.
11. **Words glued together** (`Thisproposedresearch…`) in `Table.extract()`. Build each cell's text from spans inside the cell box instead.
12. **Rows split per text line.** Merge into the previous row when the first cell is empty. In tables whose first header is "References", also merge when the previous first cell doesn't end in a year (`(2021)`).
13. **Header rows split** ("Data" / "augmentation"). A row is a header when all its spans use the header font (MuseoSans). Consecutive header rows join column by column.
14. **Phantom columns (Tables 11, 19).** An empty-header column holds part of the "Datasets" data. Merge it into the neighbouring non-empty header column with fewer conflicts.
15. **Tables that run across pages** (`TABLE n (Continued)` captions) are appended to the open table, and the repeated header is skipped.
16. **Caption ↔ table pairing.** When two tables start at the same y (p. 14), pair by horizontal overlap with the caption, not by vertical distance.

### Equations

17. **Display equations are rendered as images** (5× zoom, grayscale), and their extracted text becomes the alt. Detection: a line ending in `(n)` at the column's right edge, or MTEX math fonts, or a short centred block containing `=`. Neighbouring pieces within 8 pt are merged (fractions and sums are split into several blocks).
    The bold run-in lines in §5 ("Regression Models:") and `(Continued)` were wrongly picked up as equations before the `=` rule.

### EPUB and rendering

18. **pandoc's HTML reader drops `class` on `<p>`** but keeps it on `<div>`. The prototype wraps classed paragraphs in divs. A renderer that writes EPUB directly avoids this.
19. **Headings were shifted down one level** so numbered sections become chapters and the TOC goes two levels deep.
20. Turn off hyphenation in headings. Tables need `table-layout: fixed` with word wrapping, or 8-column tables overflow the screen.
21. Figures stay in colour (for colour Kindles). Equations are grayscale.

## Results on the fixture

- 24/24 figures, 20/20 tables and 18 numbered equations recovered.
- Word coverage: every body word of 5+ letters in the PDF appears in the HTML, apart from ligature splits and words that live inside equation images.
- About 6.3 MB EPUB without the cover, 7.7 MB with it.
