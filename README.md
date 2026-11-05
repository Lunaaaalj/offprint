# offprint

> *offprint* (n.): a separately printed copy of a single article from a journal, made for its reader.

Turn research papers into clean, reflowable Kindle books, with figures, tables, equations, a table of contents and a cover, and send them to your Kindle.

A two-column journal PDF is unreadable on a 6-inch e-ink screen. offprint rebuilds the paper's *structure* (sections, paragraphs, figures, tables, equations, references) and writes it as an EPUB that the Kindle can reflow, restyle and navigate.

> **Status: early development.** `offprint convert` turns a PDF from a supported publisher template into an EPUB with a cover. The QA gate, the JATS and LaTeX adapters and delivery are still to come.
> The roadmap is in [GitHub issues](../../issues), and implementation happens with Claude Code, issue by issue.

![Prototype output on a Kindle-sized screen](docs/kindle-preview.png)

## How it works

```
 ingest ──► resolve source ──► adapter ──► Document IR ──► render EPUB ──► QA gate ──► deliver
 (Zotero,    (best format       │          (typed blocks    (CSS, cover,    (checks,     (Send to Kindle,
  CLI,        available)        │           + assets)        Kindle quirks)  preview)     attach to Zotero)
  nvim)                         │                                             │
                ┌───────────────┼───────────────┬───────────────┐             └─► review queue
                ▼               ▼               ▼               ▼                 (fails never reach
          LaTeX source     JATS / HTML     PDF + profile    ML fallback            the Kindle)
          (arXiv)          (PMC, OA        (publisher       (Marker,
                            publishers)     template rules)  MinerU)
```

### 1. Don't parse the PDF if you don't have to

The prototype spent most of its effort recovering structure from a PDF that had thrown it away. The **resolver** tries the sources in this order and uses the first one available:

| Tier | Source | Why |
|---|---|---|
| 1 | **arXiv LaTeX source** | Exact structure, and the math as LaTeX. Most math and quant-finance papers are here. |
| 2 | **JATS XML** (PubMed Central, open-access publishers) | Sections, figures, tables and references are already labelled. |
| 3 | **PDF + publisher profile** | What the prototype does, made declarative per journal template. |
| 4 | **ML layout fallback** (Marker / MinerU) | Handles unknown templates. Slower, and its mistakes vary. |

### 2. The document IR is the contract

Every adapter writes the same intermediate representation. Only the renderer knows about EPUB and Kindle.

```
Document
├── meta: title, authors[], journal, year, doi, arxiv_id, license, abstract, keywords[]
├── blocks: [
│     Heading(level, runs, number?)
│     Paragraph(runs: [Text | Italic | Bold | Sup | Sub | Link | Cite | MathInline], role?)
│     ListItem(runs, ordered?, depth?)
│     Equation(alt, number?, latex?, asset?)
│     Figure(number, asset, caption, alt?)
│     Table(number, caption, header: [cell], rows: [[cell]], notes?)
│     Reference(runs, key?, doi?)
│   ]
├── assets: {id → bytes + mime}
└── provenance: per block → (adapter, page, bbox) for debugging and QA
```

[`docs/ir.md`](docs/ir.md) explains each block type. The same IR can later feed other outputs (an Obsidian note, a Markdown summary). EPUB is just the first renderer.

### 3. Profiles are config, cleanup steps are code

Everything specific to one publisher template goes in a **profile** (YAML): which font and size means which role, the header and footer bands, the column split, caption patterns, the side captions sit on. Supporting a new journal means writing a profile, not changing code.

Everything that recurs across templates is a **cleanup step** with its own unit tests: ignoring ActualText overlays, merging split captions, trimming tables that swallowed a text column, merging phantom columns, joining wrapped table rows, expanding ligatures, stripping control characters, dehyphenating, joining paragraphs across columns and pages.
[`prototype/README.md`](prototype/README.md) lists every one of these failures from the fixture paper.

### 4. The QA gate: no silent failures

Every conversion gets a machine-readable report and a score. A failing paper goes to a review queue, never to the Kindle.

- **word coverage**: body text in the source vs. text in the EPUB
- **counts**: every caption found has an extracted figure or table, and every equation number appears once
- **table checks**: same number of columns in every row, no empty header columns, no reference-table row without a year
- **figure-crop checks**: a crop never contains another figure's caption
- **validity**: every chapter is well-formed XHTML, and the book passes `epubcheck`
- **preview**: Kindle-sized page renders for a quick look

Any failure fixed by hand also adds a check for it, so the gate gets stricter over time.

### 5. Where AI fits

Not in the main conversion path, which is deterministic code: fast, cheap and reproducible. AI is the **repair loop**: when the gate fails, an agent gets the QA report and renders of the problem pages, proposes a profile change or a new cleanup step, and runs the tests. A human approves the change as a PR.

## Roadmap

| Milestone | Issues |
|---|---|
| **M1: Package the prototype** | scaffold & CLI · document IR · PDF adapter + profiles · cleanup steps · EPUB renderer · QA gate + golden test · Kindle preview · cover generator |
| **M2: Better sources** | source resolver · JATS adapter · arXiv LaTeX adapter · equation rendering |
| **M3: Automation** | Send-to-Kindle delivery · Zotero integration · CLI JSON interface for ibid.nvim · ML fallback adapter · review queue & AI repair loop |

Each item is a [GitHub issue](../../issues).

## Usage

```sh
offprint convert paper.pdf -o build/       # → build/paper.epub
offprint resolve 10.3389/frai.2026.1748985 # find the best source and cache it
offprint convert 10.3389/frai.2026.1748985 # → 10.3389_frai.2026.1748985.epub, from the cache
```

`convert` never uses the network. INPUT is a local PDF, or a DOI or arXiv id that `resolve` has already cached; an uncached identifier fails and tells you to run `resolve`. If the best cached source is LaTeX or JATS, `convert` fails and names the missing adapter (#11, #10) rather than quietly using a worse source.

| `convert` option | Effect |
|---|---|
| `-o`, `--output OUTDIR` | Where to write the book (default: the current directory). The file is `<input stem or identifier>.epub`. |
| `--no-cover` | Skip the cover. Without it, a cover that can't be made (Chromium is missing, or the layout checks fail) stops the conversion. |
| `--emit-ir` | Write `<stem>.ir.json` and `<stem>.assets/` instead of an EPUB. Takes local PDFs only. |

`convert` prints the EPUB's path on stdout, and anything the renderer had to change (`epub.*` codes) on stderr.

When the resolver has metadata for the paper, it's combined with what the adapter extracted. The other side always fills a gap:

| Wins | Fields | Why |
|---|---|---|
| Resolver | title, journal, year, volume, article id, DOI, arXiv id | A registry curates these. |
| Adapter | authors, abstract, license, keywords, source tier | The paper has more: affiliations, inline markup, the license holder. |

`offprint resolve ID` accepts a DOI, an arXiv id or URL, or a local file, and explains which source it chose in each tier. `--refresh` ignores the cache. It reads these settings:

| Setting | Meaning |
|---|---|
| `OFFPRINT_CONTACT_EMAIL` | The contact address for Unpaywall, which is skipped without one. No default. Can also be `contact_email` in the config file. |
| `OFFPRINT_CONFIG_FILE` | The config file (default: `~/.config/offprint/config.toml`). |
| `OFFPRINT_CACHE_DIR` | The cache (default: `~/.cache/offprint/`). `convert` reads it too. |

The cover needs Chromium: `uv run playwright install chromium`.

Planned:

```sh
offprint convert 2401.01234 --send         # convert and email to your Kindle
offprint preview paper.epub                # Kindle-sized screenshots
offprint watch --zotero-collection "→ Kindle"
```

## Repository layout

```
offprint/
├── README.md             this file
├── CLAUDE.md             guidance for Claude Code
├── pyproject.toml        package metadata and tool config
├── src/offprint/         the package: CLI, IR, adapters, cleanup, renderers, QA, preview, cover, profiles
├── prototype/            the throwaway scripts behind the first EPUB, plus a catalogue of failures
├── tests/fixtures/       real papers with expected counts (CC BY only)
└── docs/                 images and design notes
```

## Development

- Python ≥ 3.12, managed with `uv`. Tests with `pytest`, lint and format with `ruff`.
- Main dependencies: PyMuPDF (PDF), lxml (JATS/XHTML), Playwright + Chromium (previews and cover), Pillow.
- External tools: `epubcheck` (QA). pandoc only if an adapter needs it; the EPUB writer itself shouldn't depend on it (see #5).
- Workflow: issue-driven, one branch and one PR per issue, [Conventional Commits](https://www.conventionalcommits.org/), protected `main`.

### Commands

```sh
uv sync                      # install
uv run pytest                # tests
uv run ruff check . && uv run ruff format --check .
uv run offprint --version
```

`offprint preview` exists but exits with a "not implemented" message until #7 lands.

## Fixtures and licensing

Fixtures must be openly licensed papers (CC BY or similar), stored unmodified with a `SOURCE.md` giving the citation and license.
The first fixture is Nibila & Sivagami (2026), *Front. Artif. Intell.* 9:1748985, CC BY 4.0.
Generated EPUBs are for personal reading. Covers deliberately leave out publisher logos and branding.
