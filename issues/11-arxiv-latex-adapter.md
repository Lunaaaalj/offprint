# arXiv LaTeX source adapter

Labels: enhancement, area:sources
Milestone: M2: Better sources
Depends on: #2, #9, #12

Tier 1. For math-heavy papers (most of the target reading) LaTeX is the only source that keeps equations exact.

## Scope

- Unpack the e-print (tarball, a single gzipped `.tex`, or PDF-only submissions, which fall back to tier 3) and find the main file (`\documentclass` + `\begin{document}`).
- Conversion approach, to decide in the PR with a short comparison: LaTeXML, pandoc's LaTeX reader, or a hybrid. Criteria: structure fidelity, coverage of macros and environments, handling of custom macros (`\newcommand`, `.sty` files shipped in the tarball), speed.
- Map to the IR: sectioning, theorem-like environments (theorem/lemma/proof/definition → a styled `Paragraph(role=…)` or a new block type, proposed via an #2 follow-up), `equation`/`align`/`gather` (with numbers and labels) → `Equation(latex=…)`, figures (convert PDF/EPS graphics to PNG), tables (`tabular` → `Table` where possible, otherwise render as an image), bibliography (`.bbl` preferred).
- Robustness: when an environment or macro isn't understood, render that fragment as an image (compile a standalone snippet) and record a QA warning, rather than dropping it.

## Acceptance criteria

- [ ] Two fixtures (CC BY arXiv papers): one heavy on theorems and proofs (math), one with figures and tables (applied).
- [ ] Every numbered equation in the source appears exactly once in the IR with its LaTeX.
- [ ] QA passes, and the list of unsupported macros is in the report.

## Out of scope

Compiling the whole paper. Non-arXiv LaTeX (works the same, just a local `.tar.gz` input).
