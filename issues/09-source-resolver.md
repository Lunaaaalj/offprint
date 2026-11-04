# Source resolver: from a DOI, arXiv id or file to the best source

Labels: enhancement, area:sources
Milestone: M2: Better sources
Depends on: #2

`offprint convert` should accept a DOI, an arXiv id or URL, or a local file, and pick the best available source tier (README §1). This is the stage that gets most papers off the fragile PDF path.

## Scope

- Input detection: DOI (bare or `doi.org` URL), arXiv id (new and old style, with version) or `arxiv.org/abs|pdf` URL, local `.pdf` / `.xml` / `.tar.gz`.
- Metadata lookup: Crossref (DOI), the arXiv API (arXiv id). Fill `Meta` even when the content later comes from a PDF.
- Candidate sources, in tier order:
  1. arXiv e-print source tarball (when the paper has an arXiv id, including a DOI that maps to an arXiv preprint)
  2. JATS XML: PubMed Central / Europe PMC full-text XML, then the publisher's own JATS if offered
  3. PDF: the local file, or an open-access PDF (Unpaywall-style lookup; needs a contact email in config)
- A local cache (`~/.cache/offprint/`) keyed by identifier, so reruns are offline.
- `offprint resolve ID` prints the candidates and the choice, without converting.
- Polite networking: user agent with a contact address from config, rate limiting, timeouts, and a clear error per failed source.

## Acceptance criteria

- [ ] Unit tests with recorded HTTP responses (no live network in CI) for: an arXiv-only paper, a PMC paper with JATS, and the fixture DOI.
- [ ] `offprint resolve` explains why each tier was or wasn't used.
- [ ] Resolution is separate from conversion: `convert` on a resolved cache entry makes no network calls.

## Out of scope

Paywalled access, institutional proxies, scraping publisher HTML.
