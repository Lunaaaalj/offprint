# Machine-readable CLI for editor integrations (ibid.nvim)

Labels: enhancement, area:delivery
Milestone: M3: Automation
Depends on: #6, #13

Let ibid.nvim (and other editors or scripts) drive offprint: "send the paper under the cursor to my Kindle".

## Scope

- `--json` on `convert`, `resolve`, `send` and `status`: one JSON object on stdout (verdict, paths, QA summary, delivery result) and human logs on stderr. Document the schema in `docs/cli-json.md`.
- `offprint status ID`: has this paper been converted or sent, which version, and the QA verdict (from the delivery log, #13).
- Stable exit codes: 0 ok, 2 needs review, 3 resolve failed, 4 delivery failed, 1 other.
- A follow-up issue in `Lunaaaalj/ibid.nvim` describing the command it would call (`:Ibid kindle` → `offprint convert <doi|arxiv|pdf> --send --json`). Link it here.

## Acceptance criteria

- [ ] JSON schema tests for every command's output.
- [ ] The ibid.nvim issue is filed and linked.

## Out of scope

Implementing the Neovim side (that's ibid.nvim's repo).
