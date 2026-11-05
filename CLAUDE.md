# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

offprint converts research papers (PDF, JATS XML, arXiv LaTeX) into reflowable EPUBs for Kindle. It works through a document IR, a QA gate and automated delivery. Read `README.md` for the architecture and `prototype/README.md` for the catalogue of real failures the design has to handle.

## How work happens here

- **Issue-driven.** The roadmap is GitHub issues (`gh issue list`). Work on one issue at a time and check its acceptance criteria and "Out of scope" list. Out-of-scope ideas become new issues, not scope creep.
- **One branch and one PR per issue.** Name the branch `NN-short-slug`. `main` is protected.
- **Conventional Commits** (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`), referencing the issue (`Closes #N`).
- Update the GitHub issue if the scope changes.

## Design rules (don't break these without discussing first)

1. **Adapters only produce the IR; renderers only consume it.** No EPUB/HTML knowledge in adapters, no PDF knowledge in renderers.
2. **Publisher-specific values go in profiles (YAML), never in code.** If you're about to write a font name, a point size or a page coordinate in Python, it belongs in a profile.
3. **Every cleanup step is a pure function on IR or extraction data, with its own unit test**, ideally built from a minimal reproduction of the fixture failure it fixes.
4. **The main conversion path is deterministic.** No network calls or LLM calls inside `convert`. The source resolver (network) and the AI repair loop are separate stages.
5. **No silent failures.** A problem the code can detect becomes a QA check with a stable id. Fixing a bug by hand means adding the check that would have caught it.
6. **Keep provenance** (adapter, page, bbox) on IR blocks so QA reports can point at the exact place in the source.

## The prototype

`prototype/` is a reference, not a base to build on. Port ideas from it into the package with tests, and don't import from it. It reproduces the fixture EPUB with:

```sh
OUT=build prototype/build.sh tests/fixtures/frontiers-frai-2026-1748985/paper.pdf
```

When porting a heuristic, find its entry in `prototype/README.md` ("What the fixture taught us") and turn that entry into a test.

## Fixtures

`tests/fixtures/<slug>/` holds `paper.pdf` (or `.xml` / `.tar.gz`) unmodified, plus a `SOURCE.md` with the citation, license and expected counts. Only openly licensed papers. The golden test compares structural counts and QA results, not byte-identical EPUBs.

## Commands

```sh
uv sync                      # install
uv run pytest                # tests
uv run ruff check . && uv run ruff format --check .
uv run offprint --version
```

Ruff skips `prototype/`. The other commands:

```sh
uv run offprint convert INPUT [-o OUTDIR] [--no-cover]  # a local PDF or a cached identifier, to an EPUB
uv run offprint convert paper.pdf --emit-ir             # write the IR as JSON instead
uv run offprint resolve ID [--refresh]                  # the networked stage: find and cache a source
uv run offprint preview EPUB                            # Kindle-sized page previews
```

`src/offprint/pipeline.py` connects the stages. `cli.py` stays a thin wrapper over it.
