# Issue drafts

Each file is one GitHub issue: the first line is the title (`# …`), followed by `Labels:`, `Milestone:` and an optional `Depends on:` line, then the body.
`publish.py` creates the labels, milestones and issues in file order, so `NN-*.md` becomes issue `#NN` on a fresh repo. Edit a draft and its issue together.

| # | Issue | Milestone |
|---|---|---|
| 01 | Scaffold the package, CLI and CI | M1 |
| 02 | Document IR: typed blocks, assets, provenance | M1 |
| 03 | PDF adapter driven by publisher profiles | M1 |
| 04 | Generic cleanup steps, each with a regression test | M1 |
| 05 | EPUB 3 renderer from the IR | M1 |
| 06 | QA gate: checks, report, score, golden test | M1 |
| 07 | Kindle preview renderer | M1 |
| 08 | Cover generator | M1 |
| 09 | Source resolver: from a DOI, arXiv id or file to the best source | M2 |
| 10 | JATS XML adapter | M2 |
| 11 | arXiv LaTeX source adapter | M2 |
| 12 | Equation rendering strategy (LaTeX → Kindle) | M2 |
| 13 | Delivery: Send to Kindle by email | M3 |
| 14 | Zotero integration: watch a collection, attach the EPUB back | M3 |
| 15 | Machine-readable CLI for editor integrations (ibid.nvim) | M3 |
| 16 | ML layout fallback adapter (Marker / MinerU) | M3 |
| 17 | Review queue and AI repair loop | M3 |

Suggested order: 01 → 02 → (03 ∥ 04) → 05 → 06, then 07/08 at any point after 05. M2 and M3 follow.

```sh
python issues/publish.py Lunaaaalj/offprint            # dry run
python issues/publish.py Lunaaaalj/offprint --apply    # needs gh, authenticated
```
