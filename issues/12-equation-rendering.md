# Equation rendering strategy (LaTeX → Kindle)

Labels: enhancement, area:render
Milestone: M2: Better sources
Depends on: #5

Kindle's MathML support is inconsistent, so equations ship as images with the LaTeX as `alt` text. This issue builds one shared renderer for every adapter that has LaTeX (#10, #11). The PDF adapter keeps cropping.

## Scope

- `Equation(latex)` → image: compare a TeX toolchain (standalone `latex` + `dvisvgm`/`dvipng`) with a pure-Python or JS renderer (MathJax via Node, or matplotlib mathtext for simple cases). Pick by quality and dependency cost and document the choice.
- Output PNG (safe everywhere) at a resolution tuned for 300 ppi e-ink, black on transparent. Consider SVG with a PNG fallback if the renderer and Kindle agree.
- Inline math: small images aligned to the baseline (`vertical-align` from the renderer's depth metric), or Unicode text when the expression is simple (`x_i`, Greek letters, operators).
- Macro preamble support (the paper's `\newcommand`s, passed through from #11).
- Cache rendered equations by the hash of (latex, preamble, settings).

## Acceptance criteria

- [ ] A test corpus of ~30 equations (fractions, sums, matrices, cases, aligned systems, inline) renders without errors. A contact sheet goes in the PR.
- [ ] Inline equation images sit on the text baseline in the preview (#7).

## Out of scope

Editable math on Kindle.
