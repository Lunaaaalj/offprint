# The document IR

The IR (`offprint.ir`) is the contract between adapters and renderers. Adapters write it and know nothing about EPUB. Renderers read it and know nothing about PDF.

Everything is a frozen dataclass and every sequence is a tuple, so cleanup steps return a new document with `dataclasses.replace`. Pass tuples, not lists: a list won't compare equal after a JSON round-trip.

## Blocks

Every block has an `id`, unique in the document, and `Document.provenance[id]` says where it came from.

| Block | Use it for | Notes |
|---|---|---|
| `Heading(level, runs, number?)` | Section titles | `level` starts at 1. `number` is the label from the source ("2.1"), not part of `runs`. |
| `Paragraph(runs, role?)` | Running text | `role`: `body` (default), `abstract`, `small` (footnote-size text such as credits) or `meta` (front matter such as a citation line). |
| `ListItem(runs, ordered?, depth?)` | One list entry | Consecutive items form a list. `depth` starts at 0. |
| `Equation(alt, number?, latex?, asset?)` | Display math | Needs `latex`, an image `asset` or both. PDF adapters crop an image and put the extracted text in `alt`. LaTeX and JATS adapters set `latex`. |
| `Figure(number, asset, caption, alt?)` | A captioned image | `alt` holds recovered alt-text, such as the PDF's ActualText. |
| `Table(number, caption, header, rows, notes?)` | Real tabular data | Every row has as many cells as `header`. Expand spanning cells when mapping a source. A table that can't be represented cell by cell should become a `Figure`. |
| `Reference(runs, key?, doi?)` | One bibliography entry | `key` is what `Cite.target` points to, when the source has one. |

Math inside a sentence is a `MathInline` run, not an `Equation`.

Numbers are strings, because papers have "S1", "A.2" and "12a".

## Runs

Inline content is a tuple of runs. `Italic`, `Bold`, `Sup`, `Sub`, `Link(href, runs)` and `Cite(target, runs)` hold more runs, so they nest (italic inside a link). `Text(text)` and `MathInline(text, latex?)` are the leaves. Table cells are also tuples of runs.

## Meta, assets and provenance

- `Meta` holds the bibliographic data. `source_tier` is `latex`, `jats`, `pdf` or `ml`, and `license` has an SPDX id and a holder.
- `Document.assets` maps an id to an `Asset(id, mime, bytes, width?, height?)`. The key must equal `asset.id`. Blocks refer to assets by id.
- `Provenance(adapter, page?, bbox?, note?)` lets a QA report point at the exact place in the source. `page` is 1-based.

## Saving to JSON

```python
text = to_json(doc, assets_dir)
doc = from_json(text, assets_dir)
```

The JSON carries an `ir_version`, and `from_json` raises `IRFormatError` for anything it can't read. Asset bytes go in `assets_dir`, in files named by their SHA-256, so identical images are stored once and asset ids are never used as paths. `to_json` doesn't delete files, so reuse a directory only for the same document.

## Validating

`validate(doc)` returns a list of `Problem(code, message, block_id?)`. An empty list means the document is valid. Codes are stable:

| Code | Rule |
|---|---|
| `block.duplicate_id` | Block ids are unique. |
| `provenance.missing` | Every block has provenance. |
| `provenance.unknown_block` | Provenance only describes blocks that exist. |
| `asset.unresolved` | Every asset reference resolves. |
| `asset.id_mismatch` | Each asset is stored under its own id. |
| `figure.duplicate_number`, `table.duplicate_number` | Numbers are unique per kind. A figure and a table can share one. |
| `table.width` | Every row is as wide as the header. |
| `equation.empty` | An equation has `latex` or an `asset`. |
| `heading.level` | Heading levels start at 1. |
| `heading.jump` | Levels go down by at most 1 at a time, starting from level 1. Going back up is free. |

`Cite.target` isn't checked against `Reference.key`, because a PDF adapter often can't link them.
