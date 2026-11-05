# Fixture: frontiers-frai-2026-1748985

`paper.pdf` is:

> Nibila Y and Sivagami M (2026). Artificial intelligence techniques for classification of Alzheimer's disease using neuroimaging data: a review. *Front. Artif. Intell.* 9:1748985. doi: [10.3389/frai.2026.1748985](https://doi.org/10.3389/frai.2026.1748985)

© 2026 Nibila and Sivagami. Open access under the [Creative Commons Attribution License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
It's included unmodified as a test fixture.

Why it's a good first fixture: a two-column Frontiers template, 35 pages, 24 figures (photos, bar and line charts, diagrams), 20 tables (two with phantom columns, two running over several pages, one wrongly detected as swallowing the next column), 18 numbered display equations, and hidden ActualText overlays on every chart.
See `prototype/README.md` for the full list of failures.

## The JATS copy

`paper.xml` is the same article as PubMed Central holds it, PMC13223030, retrieved unmodified on 2026-11-04 from NCBI efetch, which is what `offprint resolve` gets for this DOI because Europe PMC answers HTTP 500. It keeps efetch's `<pmc-articleset>` wrapper.

`graphics/` holds its 24 figures, unmodified, from the [PMC Open Access dataset](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/) (`s3://pmc-oa-opendata/PMC13223030.1/`). The dataset's record lists the license as CC BY, and each file matched the MD5 sum in that record. The same license as the PDF applies.

Two things in the XML to know about:

- `<equation-count>` says 19, but the article has 18 `<disp-formula>`, 18 MathML equations and 18 numbers, like the PDF.
- The figures' `<alt-text content-type="machine-generated">` can't be trusted: Figures 1 to 5 describe another paper's policy diagrams. The adapter ignores machine-generated alt text.

Expected counts, for the golden test:

| | count |
|---|---|
| pages | 35 |
| figures | 24 |
| tables | 20 |
| numbered display equations | 18 |
| top-level sections (incl. back matter) | 15 |
| references | 109 |
| list items (JATS only: the PDF path finds 14) | 31 |

How the two paths compare, as a share of each one's lower-cased words found in the other (`test_jats_fixture.py`). This compares the two IRs, not either one against the source:

| | of JATS in PDF | of PDF in JATS |
|---|---|---|
| headings, paragraphs and lists | 99.79% | 99.08% |
| table cells and captions | 100% | 100% |
| references | 99.98% | 97.91% |

The PDF's "Edited by" and "Reviewed by" credits and the "and" before each last author aren't in the same place or form, which accounts for most of the gap.
