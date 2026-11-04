# Document IR: typed blocks, assets, provenance

Labels: enhancement, area:ir
Milestone: M1: Package the prototype
Depends on: #1

The IR is the contract between adapters (PDF, JATS, LaTeX, ML) and renderers (EPUB, and later others). Get it right before porting anything.

## Scope

Dataclasses (or attrs/pydantic, your choice, justify it in the PR) for the structure sketched in the README:

- `Document(meta, blocks, assets, provenance)`
- `Meta`: title, authors (name, affiliation?, corresponding?), journal, year, volume/article id, doi, arxiv_id, license (SPDX id + holder), abstract (runs), keywords, `source_tier`.
- Blocks: `Heading(level, number?, runs)`, `Paragraph(runs, role?)` (role: body | abstract | small | meta), `ListItem(runs, ordered, depth)`, `Equation(number?, latex?, asset?, alt)`, `Figure(number, asset, caption, alt?)`, `Table(number, caption, header, rows, notes?)`, `Reference(runs, key?, doi?)`.
- Inline runs: `Text`, `Italic`, `Bold`, `Sup`, `Sub`, `Link(href)`, `Cite(target)`, `MathInline(latex?, text)`. Runs nest (italic inside a link, and so on).
- `Asset(id, mime, bytes, width?, height?)`, stored by id. Blocks point to assets by id.
- `Provenance(adapter, page?, bbox?, note?)` attached to each block by id.
- JSON round-trip (`to_json` / `from_json`) so IRs can be saved, diffed and used as test fixtures. Assets go in a sibling directory, not base64 in the JSON.
- `validate(doc)`: every asset reference resolves, figure and table numbers are unique, every table row has the same width as its header, heading levels don't jump by more than 1.

## Acceptance criteria

- [ ] Round-trip property test: `from_json(to_json(doc)) == doc` for generated documents (hypothesis or hand-built cases).
- [ ] `validate` has a test for each rule, each with a failing example.
- [ ] A short `docs/ir.md` explains each block type and when an adapter should use it.

## Out of scope

Any adapter or renderer. Cross-references between blocks (equation and figure links) can be a follow-up issue.
