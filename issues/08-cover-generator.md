# Cover generator

Labels: enhancement, area:render
Milestone: M1: Package the prototype
Depends on: #2

Generate a 1600×2560 cover (Amazon's recommended Kindle ratio) from the IR's metadata and one hero image. Port `prototype/cover.py` (example in `docs/cover-example.png`).

## Scope

- Template: duotone hero with vignette, a seeded network motif (seeded from the DOI so it's stable per paper), kicker (article type), title, authors, citation and license footer.
- Hero selection: prefer photo-like figures (high colour/texture variance, not a chart), then a diagram, then no hero (the motif alone). Make the heuristic swappable.
- Title fitting: shrink the font size or wrap so long titles fit in the title box. Truncate authors to "A, B, … & Z" when there are more than 4.
- Must stay legible in grayscale. Test it by computing contrast after grayscale conversion.
- No publisher logos or branding. Only the citation text.

## Acceptance criteria

- [ ] Fixture → a cover similar to `docs/cover-example.png`.
- [ ] A synthetic IR with a 200-character title and 12 authors still lays out without overflow (checked from the rendered DOM boxes).
- [ ] A paper with no figures gets a motif-only cover.

## Out of scope

Multiple themes (later, if wanted).
