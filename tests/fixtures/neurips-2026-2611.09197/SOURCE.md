# Fixture: neurips-2026-2611.09197

`paper.pdf` is arXiv:2611.09197v1, the PDF as arXiv serves it (`https://arxiv.org/pdf/2611.09197`), unmodified:

> Ascari G L, Tamassia I, Jiao Y, De Raedt L and Marra G (2026). Safe Reinforcement Learning via Probabilistic Option Shielding. arXiv:2611.09197v1 [cs.AI], 6 Nov 2026. Accepted at the NEmo workshop @ NeurIPS 2026.

The abstract page, <https://arxiv.org/abs/2611.09197>, lists the license as [Creative Commons Attribution 4.0 (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). Checked on 2026-11-09.
The PDF itself carries no license text, so the converter can't know it (see "What the report still lists").

Why it's a good second fixture: the NeurIPS template, which is **one column** (the Frontiers fixture is two), set in Times (Nimbus Roman) with Computer Modern maths that is also used inline.
It has 18 pages, 11 figures (several with sub-figures), 6 booktabs tables, 7 numbered display equations plus unnumbered ones, appendices numbered with letters (`B.1`), an author-year reference list, a two-line title and five authors each with their own affiliation.
The profile is `src/offprint/profiles/neurips.yaml`; it is picked from the fonts and the "Conference on Neural Information Processing Systems" line on page 1.

Expected counts, for the golden test (`tests/test_neurips_fixture.py`):

| | count |
|---|---|
| pages | 18 |
| figures | 11 |
| tables | 6 |
| numbered display equations | 7 |
| top-level sections (incl. appendices and references) | 12 |
| references | 34 |

## What the report still lists

The verdict is `review`, and the test pins exactly these three checks, so that fixing one makes it fail and the entry goes:

- `table.empty_header` and `pdf.dropped_text`: booktabs tables have few ruled lines, so detection splits and drops rows. Tracked in #36 and #37.
- `meta.required`: no license, because an arXiv PDF has none printed. Not tracked yet.
