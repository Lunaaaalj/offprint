# PDF adapter driven by publisher profiles (port the prototype)

Labels: enhancement, area:pdf
Milestone: M1: Package the prototype
Depends on: #2

Port `prototype/convert.py` into `adapters/pdf/`, producing the IR. Pull every value specific to the Frontiers template out into a profile.

## Scope

- **Profile format** (YAML in `src/offprint/profiles/`), with a schema and validation. At minimum:
  - `match`: how to detect the template (PDF producer/creator, fonts present, text patterns like `frontiersin.org` in the footer).
  - `page`: header/footer bands, column split x, column boxes, first-page sidebar box and which sidebar fields to keep (CITATION, COPYRIGHT).
  - `roles`: font family + size range → role (`title`, `h1`, `h2`, `h3`, `authors`, `affiliation`, `abstract`, `body`, `caption`, `table_header`, `table_body`, `reference`, `ignore` such as Calibri chart labels).
  - `captions`: regex for figure and table captions, which side captions sit on (`below` for figures and `above` for tables here), the continuation marker (`(Continued)`).
  - `equations`: math font names, equation-number pattern.
- **`profiles/frontiers.yaml`** reproduces the prototype's behaviour.
- **Adapter pipeline**: extract spans (with `TEXT_IGNORE_ACTUALTEXT`) → classify roles → detect figures, tables and equations → order reading → emit IR blocks with provenance. Call the generic steps from `cleanup/` (#4). Don't reimplement them here.
- Figure crops keep colour. Equation crops are grayscale with a configurable zoom.
- Chart alt-text recovered from ActualText goes into `Figure.alt`.
- `offprint convert paper.pdf --emit-ir` writes the IR JSON (useful before #5 exists).
- If no profile matches, fail with a clear error naming the closest profile. The ML fallback is #16.

## Acceptance criteria

- [ ] On the fixture: 24 figures, 20 tables, 18 numbered equations and 15 top-level sections, each with the correct number and caption text.
- [ ] No font names, point sizes or coordinates in the Python code under `adapters/pdf/`. Grep for it in a test.
- [ ] The IR passes `validate` (#2).
- [ ] Each prototype heuristic that lives here (not in `cleanup/`) has a unit test built from a minimal reproduction.

## Out of scope

Other publishers' profiles (one issue per template, later). Rendering.
