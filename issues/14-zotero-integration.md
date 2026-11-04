# Zotero integration: watch a collection, attach the EPUB back

Labels: enhancement, area:delivery
Milestone: M3: Automation
Depends on: #9, #13

The everyday workflow: drop a paper into a Zotero collection like "→ Kindle", and it arrives on the Kindle. The EPUB is attached back to the item.

## Scope

- Read items in a named collection: DOI, arXiv id (from the URL or `extra`), and the attached PDF path.
  Options: Zotero 7's local API (read-only, must be enabled in settings), or reading a *copy* of `zotero.sqlite` the way ibid.nvim does. Pick one and justify it. Never write to the live database.
- `offprint watch --zotero-collection NAME [--interval 10m]`: convert new or changed items (resolver first, attached PDF as the tier-3 fallback), deliver passing ones (#13), queue the rest (#17).
- Write-back: attach the EPUB (and optionally `qa.md`) to the item through the Zotero Web API (needs an API key with write access, stored in the keychain). Add a tag: `offprint:sent` / `offprint:review`.
- Idempotent: state keyed by item key + attachment hash.
- Optional launchd plist / systemd unit example for running `watch` in the background.

## Acceptance criteria

- [ ] Tests against a fixture `zotero.sqlite` copy (a few items) and a mocked Web API.
- [ ] Re-running `watch` with no changes does nothing.

## Out of scope

A Zotero plugin. Syncing annotations.
