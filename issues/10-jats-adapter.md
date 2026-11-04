# JATS XML adapter

Labels: enhancement, area:sources
Milestone: M2: Better sources
Depends on: #2, #9

JATS is what most open-access publishers and PMC deposit. It already labels sections, figures, tables and references, so this adapter is mostly a mapping, not guesswork. It's tier 2 in the resolver.

## Scope

- Map `front` → `Meta` (title, contrib-group, aff, pub-date, article-id doi, permissions/license, abstract, kwd-group).
- Map `body` → blocks: `sec`/`title` → `Heading` (numbering from `label`), `p`, `list`/`list-item`, `fig` (label, caption, `graphic` href), `table-wrap` (HTML-ish `table` → `Table`, keeping `colspan`/`rowspan` by expanding or recording them), `disp-formula` (MathML and/or `tex-math` → `Equation.latex`, image fallback), inline `italic`/`bold`/`sup`/`sub`/`xref`/`ext-link`/`inline-formula`.
- `back`/`ref-list` → `Reference` with DOI when present. `ack`, `fn-group`, funding and conflict-of-interest sections become back-matter headings.
- Fetch figure graphics referenced by `xlink:href` (via the resolver's cache).
- A JATS fixture: a CC BY article's XML + graphics in `tests/fixtures/`. Ideally the same Frontiers paper if its JATS is available, so the PDF and JATS paths can be compared on equal terms.

## Acceptance criteria

- [ ] JATS fixture → IR that passes `validate`, with figure, table and equation counts matching the article.
- [ ] The QA gate (#6) passes on it.
- [ ] If the same paper exists as both a PDF fixture and a JATS fixture, a test reports the coverage difference between the two paths.

## Out of scope

Non-JATS publisher HTML.
