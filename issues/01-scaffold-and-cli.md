# Scaffold the package, CLI and CI

Labels: enhancement, area:infra
Milestone: M1: Package the prototype

Create the Python package everything else lives in. Nothing clever here: a layout that later issues can fill in without rearranging.

## Scope

- `pyproject.toml` (Python ≥ 3.12, managed with `uv`), package in `src/offprint/`, console script `offprint`.
- Module skeleton with empty or stub modules and docstrings stating each module's job:
  `ir/` (#2), `adapters/pdf/` (#3), `cleanup/` (#4), `render/epub/` (#5), `qa/` (#6), `preview/` (#7), `cover/` (#8), `profiles/` (YAML files, #3).
- CLI with Typer or argparse: `offprint convert INPUT [-o OUTDIR]`, `offprint preview EPUB`, `offprint --version`. Until #3 and #5 land, `convert` exits with a clear "not implemented" message.
- `pytest` set up with one smoke test (`offprint --version`), plus a `fixtures` helper that finds `tests/fixtures/<slug>/`.
- `ruff` (lint + format) configured in `pyproject.toml`.
- GitHub Actions: on PRs and pushes to `main`, run `uv sync`, `ruff check`, `ruff format --check` and `pytest` on ubuntu-latest.

## Acceptance criteria

- [ ] `uv sync && uv run offprint --version` works on a clean clone.
- [ ] `uv run pytest` passes and CI is green.
- [ ] The README's "Commands" section and CLAUDE.md's match reality.

## Out of scope

Any conversion logic. Packaging for PyPI.
