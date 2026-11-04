# Review queue and AI repair loop

Labels: enhancement, area:qa
Milestone: M3: Automation
Depends on: #6, #7

Papers that fail QA wait in a queue with everything needed to fix them. An AI agent can propose the fix (a profile change or a new cleanup step); a human approves it as a PR.

## Scope

- Queue directory per paper: source, IR JSON, `qa.json`/`qa.md`, previews of the flagged pages (#7), and crops of the source PDF pages at the flagged bboxes.
- `offprint review list | show ID | retry ID | dismiss ID`.
- `offprint review prompt ID` writes a self-contained task brief for a coding agent (Claude Code): the failing checks, the provenance crops, the relevant profile, links to the matching `prototype/README.md` entries, and the rule that every fix includes a regression test plus, if the failure was silent, a new QA check.
- Docs: how to run the repair loop with Claude Code (`claude -p "$(offprint review prompt ID)"` or interactively), and how to turn the result into a branch + PR that follows the repo's conventions.
- After a fix merges, `offprint review retry --all` reconverts queued papers.

## Acceptance criteria

- [ ] An end-to-end test with a deliberately broken profile: the paper is queued, `prompt` produces a brief that names the failing check and page, and `retry` succeeds after the profile is fixed.

## Out of scope

Running the agent automatically without a human approving the change.
