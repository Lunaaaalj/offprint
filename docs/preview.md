# Kindle previews

`offprint preview book.epub` renders Kindle-sized pages to PNGs, for a quick look at the pages that matter. It's an approximation: the pagination is CSS columns in Chromium with a free Bookerly lookalike, not a Kindle's layout engine, so line breaks and page breaks won't match a real device. Use it to see whether a page looks right, not to count pages.

```sh
offprint preview build/paper.epub                       # the automatic selection
offprint preview build/paper.epub --pages 3:2 --pages 0:1
offprint preview build/paper.epub --bezel --grayscale   # a device around an e-ink look
```

It needs Chromium (`uv run playwright install chromium`). The pages print on stdout, one path per line, with the contact sheet last.

| Option | Effect |
|---|---|
| `-o`, `--output OUTDIR` | Where to write the pages (default: `<stem>.preview/` next to the EPUB). |
| `--pages CHAPTER:PAGE` | Render this page instead of the automatic selection. Can be repeated. |
| `--qa QA_JSON` | The QA report to read (default: `<stem>.qa.json` next to the EPUB, if there is one). |
| `--bezel` | Draw a device around each page. |
| `--grayscale` | Turn each page grey on a paper tint. |

`CHAPTER` is the number in `chapter-NN.xhtml`, 0 for the front matter, or the file's name. Pages count from 1.

## Which pages

Without `--pages`:

- the first page of the book after the cover
- the first page with a figure, with an equation and with a table
- every page behind a finding in `qa.json`, using its `location` ([qa.md](qa.md#finding-a-flagged-page))

A finding with a `fragment` shows the page that element starts on. One with only a `file` shows that file's first page. A finding with no place in the book has no page, and `preview` says how many there were on stderr.

## What it writes

- One PNG per page, 1236×1647 (412×549 CSS pixels at 3×, a Paperwhite 6.8"). With `--bezel` they're larger.
- `contact-sheet.png`: all the pages together, each labelled with why it was chosen and, in red, its check ids.
- `manifest.json`, the same in a form tools can read:

```json
{
  "manifest_version": 1,
  "epub": "paper.epub",
  "device": {"width": 412, "height": 549, "scale": 3},
  "contact_sheet": "contact-sheet.png",
  "unplaced_findings": 0,
  "pages": [
    {
      "image": "03-chapter-02-p2.png",
      "file": "chapter-02.xhtml",
      "page": 2,
      "pages": 7,
      "percent": 9,
      "reasons": ["first table"],
      "checks": ["table.empty_header"]
    }
  ]
}
```

- If a `<stem>.qa.md` is next to the report, a "Preview" section in it that links each page with its check ids. Running `preview` again replaces that section.

The screen's measurements and the contact sheet's layout are in [`src/offprint/preview/device.yaml`](../src/offprint/preview/device.yaml). The status bar shows the pages left in the chapter and the percentage through the book, both counted from these renders, and a fixed time so renders are reproducible.

The font is the Literata bundled for the cover, under the OFL (`src/offprint/cover/assets/fonts/OFL.txt`). It has regular and bold, so italics are slanted by the browser.
