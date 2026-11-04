# QA gate: checks, report, score, golden test

Labels: enhancement, area:qa
Milestone: M1: Package the prototype
Depends on: #3, #5

No silent failures. Every conversion produces `qa.json` + `qa.md`, and a pass/fail decision that later stages (delivery #13, review queue #17) act on.

## Scope

Checks, each with a stable id, a severity (error/warn) and a pointer to provenance (page, bbox):

- `coverage.words`: body words (≥ 5 letters) in the source vs. the EPUB text, after ligature normalisation. Excludes words inside equation images. Threshold set in config.
- `counts.figures` / `counts.tables`: captions found == blocks extracted, numbered 1..n with no gaps or duplicates.
- `counts.equations`: equation numbers 1..n each appear once.
- `table.width`: every row matches the header width.
- `table.empty_header`: no empty header cells (the phantom column symptom).
- `table.ref_rows`: in tables whose first header is "References", every first cell ends in a year.
- `figure.foreign_caption`: a figure crop contains no other caption's text.
- `xhtml.wellformed` on every chapter, and `epubcheck` (skipped with a warning if not installed).
- `meta.required`: title, at least one author, and a license are present.

Plus:
- Score and verdict: `pass` / `review`. Any error means `review`.
- `offprint convert` prints a one-screen summary and exits non-zero on `review` (with `--allow-review` to override).
- **Golden test** on the fixture: verdict `pass`, the expected counts from `SOURCE.md`, coverage ≥ the threshold.
- **Mutation tests**: deliberately break the IR (drop a figure, add a phantom column, inject a control character) and assert the right check fires.

## Acceptance criteria

- [ ] All checks above are implemented and each has a mutation test.
- [ ] The golden test passes in CI.
- [ ] `qa.md` is readable on its own: what failed, where (page number), and a hint.

## Out of scope

Visual diffing of renders. The review queue UI (#17).
