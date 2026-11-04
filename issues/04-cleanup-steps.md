# Generic cleanup steps, each with a regression test

Labels: enhancement, area:pdf
Milestone: M1: Package the prototype
Depends on: #2

The fixes that recur across templates. Each is a small pure function with its own test built from the matching entry in `prototype/README.md` ("What the fixture taught us").

## Scope

Text:
- [ ] ligature expansion and combining-mark fixes (`¸S` → `Ş`)
- [ ] control-character stripping (the bug that silently dropped a whole chapter)
- [ ] whitespace collapsing for justified text
- [ ] dehyphenation (join only before a lowercase continuation), with a hook for a word list so real compounds such as "magnetization-prepared" survive
- [ ] paragraph joining across columns and pages; floats that interrupt a sentence move after the paragraph; equations are never merged across

Captions:
- [ ] merge caption fragments that touch, and regroup spans into lines by y-centre then x (`FIGU` + `RE 16` + `Grap…`)

Tables:
- [ ] trim tables that swallowed a neighbouring text column
- [ ] build cell text from spans, not `Table.extract()` (glued words)
- [ ] join wrapped rows: first cell empty, or (in reference tables) the previous first cell has no year
- [ ] join consecutive header rows
- [ ] merge phantom columns: an empty-header column folds into the neighbour with fewer conflicts
- [ ] join tables continued across pages and skip repeated headers
- [ ] pair captions with tables by horizontal overlap

Each step reads its thresholds (gaps, tolerances) from the profile or an options object, not from constants scattered through the code.

## Acceptance criteria

- [ ] Every checkbox above has at least one passing unit test plus a test of the case it must *not* change.
- [ ] Steps are named and listed in a registry, so QA reports (#6) can say which steps ran.

## Out of scope

Detection logic specific to one template (that's #3's profile).
