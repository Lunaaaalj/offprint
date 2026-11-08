# The QA gate

Every `offprint convert` that produces a book also writes `<stem>.qa.json` and `<stem>.qa.md` next to it, and reaches a verdict: `pass` or `review`. Any error means `review`, whatever the score. Later stages act on the verdict: a book in review never reaches the Kindle.

`convert` still writes the EPUB on `review`, because a person needs it to look at the problem. It prints a one-screen summary on stderr and exits 3, or 0 with `--allow-review`.

| Exit code | Meaning |
|---|---|
| 0 | The book passed, or `--allow-review` was given. |
| 1 | No book was made, and nothing was written. |
| 2 | The command line was wrong. |
| 3 | The book and its reports exist, and the verdict is `review`. |

A conversion that stops before the gate writes no report. That's an invalid IR (exit 1, with `validate` codes in the message) or a cover that fails its layout checks.

## Checks

Ids are stable. Each check has a severity, `error` or `warn`, and a hint for fixing it. The list in `offprint.qa.catalog` is the source of truth, and every run reports all of its checks, in that order.

| Id | Severity | Rule |
|---|---|---|
| `coverage.words` | error | Enough of the source's words of 5+ letters reach the EPUB. See below. |
| `counts.figures` | error | Figure captions in the source == figure blocks, numbered 1..n with no gaps or duplicates. |
| `counts.tables` | error | The same for tables. "(Continued)" captions aren't new tables. |
| `counts.equations` | error | Equation numbers in the source == numbers in the IR, 1..n, once each. |
| `table.width` | error | Every row is as wide as the header. |
| `table.empty_header` | error | No empty header cells, the symptom of a phantom column. |
| `table.ref_rows` | error | In a table whose first header is "References", every first cell ends in a year. |
| `reference.numbering` | error | References numbered `[n]`, `n.`, `(n)` or `n)` run 1..n once each, and none lacks its number. Skipped when fewer than half are numbered. |
| `figure.foreign_caption` | error | A figure's box holds no other figure's or table's caption. |
| `xhtml.wellformed` | error | Every XHTML file in the book parses, and every file in the spine is there. |
| `epubcheck` | error (`warn` for its warnings) | The book passes `epubcheck`. Skipped when it isn't installed. |
| `meta.required` | error | The paper has a title, at least one author and a license. |
| `block.duplicate_id`, `provenance.*`, `asset.*`, `figure.duplicate_number`, `table.duplicate_number`, `equation.empty`, `heading.*` | error | The rest of `offprint.ir.validate`, under its own codes (see [ir.md](ir.md)). |
| `epub.invalid_xml_chars`, `epub.equation_text_fallback`, `epub.inline_math_text_fallback`, `epub.link_dropped`, `epub.asset_converted` | warn | What the renderer had to change, under its own codes. |
| `jats.unmapped_element`, `jats.figure_without_graphic`, `jats.empty_formula` | error | What the JATS adapter couldn't carry over, where content may be missing. |
| `jats.unmapped_inline`, `jats.math_fallback`, `jats.inline_graphic`, `jats.table_as_figure`, `jats.license_unknown`, `jats.no_front` | warn | What the JATS adapter carried over in a weaker form. |
| `math.renderer_unavailable`, `math.preamble_failed` | error | Equations that may be wrong or are all plain text. See [`equations.md`](equations.md). |
| `math.render_failed`, `math.system_font`, `math.cache_unwritable` | warn | One formula that stayed as text or used a system font, or a cache that couldn't be written. |
| `cover.overflow`, `cover.contrast` | error | The cover's layout. A failure stops the conversion, so in a report these are `pass`, or `skip` with `--no-cover`. |

Numbers that aren't plain integers, such as "S1" and "A.2", aren't held to the 1..n rule, but they still have to match the source.

Thresholds live in [`src/offprint/qa/thresholds.yaml`](../src/offprint/qa/thresholds.yaml), never in a check.

### Word coverage

`coverage.words` counts every occurrence, so a lost paragraph shows even if its words appear elsewhere in the book. It compares the source's reading text with the text of the EPUB's spine, after NFKC normalisation (which expands ligatures) and case folding.

The source's reading text leaves out what the adapter's profile excludes on purpose (running heads, chart labels, the first page's sidebar) and whatever the book shows as an image: text inside an equation's or a figure's box, except captions. The EPUB's text leaves out `alt` attributes.

Tables repeated across pages repeat their headers in the source, so a paper with long tables never reaches exactly 1.0.

The value is the share of source words found. When it's below the threshold, the first finding gives the total and the rest name the pages that lost the most, found by looking for words that aren't next to the same neighbour in the book.

### Sources without evidence

The checks that compare with the source need a `SourceEvidence` (`offprint.extraction`), which an adapter reads from the source apart from the IR. The PDF and JATS adapters each have a `read_evidence`. Without evidence, `coverage.words` and `figure.foreign_caption` are skipped, and the three `counts.*` checks only look at the numbering. A skip never changes the verdict, but the report lists it.

### Sources without pages

JATS has no pages, so its `SourceEvidence.pages` is `None` and its evidence has no `page` or `bbox`:

- `coverage.words` names the section that lost words instead of the page. A finding like this has no `location`.
- `counts.*` compare against the article's own labels.
- `figure.foreign_caption` is skipped, with the reason in `qa.json`. A figure is a file of its own rather than a crop of a page, so it can't take in another caption.
- `counts.pages` in `qa.json` is null, and `qa.md` doesn't mention pages.

The JATS reader walks the XML on its own, because sharing the mapper's walk would hide what the mapper loses. An element it doesn't know counts as text. It leaves out what the book has as an image (maths, alt text) and the labels the renderer writes itself. Funding and conflict statements in `article-meta` are left out too, because they can repeat a section of `back`, so losing one of those isn't noticed.

## Score

The score is the share of the checks that ran and passed, from 0 to 1, with a check that only has warnings counting as `warn_weight`. It's a number to compare over time. Nothing depends on it: the verdict comes from errors alone.

## `qa.json`

`qa.json` is the contract with later stages: the preview (#7), the source tiers (#10), delivery (#13), the ML fallback (#16) and the review queue (#17). `schema_version` is 1. Adding a key doesn't change it, and changing or removing one does.

```json
{
  "schema_version": 1,
  "verdict": "review",
  "score": 0.963,
  "title": "Artificial intelligence techniques for classification…",
  "epub": "paper.epub",
  "counts": {"pages": 35, "figures": 24, "tables": 20, "equations": 18, "sections": 15},
  "totals": {"pass": 24, "warn": 0, "fail": 1, "skip": 2},
  "checks": [
    {
      "id": "coverage.words",
      "severity": "error",
      "status": "pass",
      "findings": 0,
      "value": 0.9967,
      "threshold": 0.98,
      "reason": null
    }
  ],
  "findings": [
    {
      "check": "table.ref_rows",
      "severity": "error",
      "message": "table 6 row 1 doesn't end in a year: 'Khan et al. (2022) and performance metrics.'",
      "hint": "A first cell has no year at its end: …",
      "block_id": "table-6",
      "page": 10,
      "bbox": [304.8, 308.9, 546.0, 550.3],
      "location": {"file": "chapter-05.xhtml", "fragment": "b89"}
    }
  ]
}
```

| Key | Meaning |
|---|---|
| `verdict` | `pass` or `review`. |
| `score` | See above. |
| `title`, `epub` | The paper's title, and the book's file name (null if none). |
| `counts` | What the book holds. `pages` is the source's, and null without evidence or for a source without pages. `equations` counts numbered ones and `sections` the level-1 headings. |
| `totals` | How many checks ended in each status. |
| `checks[]` | Every check, always in the same order. |
| `checks[].status` | `pass`, `warn` (only warnings), `fail` (at least one error) or `skip`. |
| `checks[].findings` | How many findings this check has. |
| `checks[].value`, `.threshold` | The measured value and its limit, for `coverage.words`. Otherwise null. |
| `checks[].reason` | Why it was skipped. |
| `findings[]` | Everything found, in the order of `checks`. |
| `findings[].block_id` | The IR block, if there is one. |
| `findings[].page`, `.bbox` | Where in the source, from provenance: a 1-based page and points from its top left. Either can be null. |
| `findings[].location` | Where in the book. See below. |

### Finding a flagged page

`location` is how a tool gets from a finding to the page a reader sees. It's null for a finding with no place in the book.

- `file` is relative to the OPF, like the book's own links: `chapter-05.xhtml`.
- `fragment` is an element id in that file, or null, meaning the file as a whole. Paragraphs and list items have no id, so theirs is the nearest id before them. A finding with only a source page points to the first block read from that page.

`offprint preview` uses `location` to render the pages behind every finding and labels each one with its check ids. It also adds a "Preview" section to `qa.md` that links them (see [preview.md](preview.md)). `qa.json` stays as `convert` wrote it.

## Adding a check

1. Write it as a pure function in `offprint.qa` that returns an `Outcome`, reading any number from `thresholds.yaml`.
2. Add it to `CHECKS` with a stable id, a severity and a hint, and call it from `gate.py`.
3. Add a mutation test: break the fixture's IR and assert the check fires.
4. Add it to the table above.

A new `Problem` code from an adapter or the renderer is a check too, and goes in `CHECKS`. A test scans the source for codes, because the gate raises on one it doesn't know.
