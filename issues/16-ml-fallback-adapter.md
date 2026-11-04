# ML layout fallback adapter (Marker / MinerU)

Labels: enhancement, area:pdf
Milestone: M3: Automation
Depends on: #3, #6

Tier 4: PDFs from templates with no profile. Use an ML document-layout tool and map its output to the IR, so unknown journals still produce something, with QA deciding whether it's good enough.

## Scope

- Evaluate Marker and MinerU (and any strong newer option) on the Frontiers fixture *with the profile disabled*, plus two PDFs from other publishers. Compare structure, tables, equations (do they emit LaTeX?), speed on CPU vs. GPU, install size and license.
- Implement an adapter for the winner as an optional extra (`pip install offprint[ml]`), mapping its JSON/Markdown output to IR blocks with provenance.
- `offprint convert --adapter ml` forces it. The resolver uses it automatically only when no profile matches.
- Record the comparison as a table in `docs/ml-fallback.md`.

## Acceptance criteria

- [ ] On the Frontiers fixture, the ML path's QA report is generated and its gaps compared to the profile path are documented.
- [ ] The core package installs and runs without the ML extra.

## Out of scope

Training or fine-tuning models.
