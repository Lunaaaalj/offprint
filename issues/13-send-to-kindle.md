# Delivery: Send to Kindle by email

Labels: enhancement, area:delivery
Milestone: M3: Automation
Depends on: #6

`offprint convert … --send` and `offprint send book.epub`: email the EPUB to the user's Send-to-Kindle address. Only books that passed QA are sent automatically.

## Scope

- Config file (`~/.config/offprint/config.toml`): Kindle address, SMTP settings, sender. Secrets come from the OS keychain (`keyring`) or env vars, never the config file.
- Use the sender address the user has approved in Amazon's "Approved Personal Document E-mail List". The docs explain this one-time setup.
- Respect the attachment size limit (check Amazon's current limit and document it). When over, downscale figures (re-render through #5 with a lower max width) before failing.
- `--dry-run` writes the `.eml` instead of sending.
- Delivery log (`~/.local/share/offprint/deliveries.jsonl`): identifier, file hash, time and result, so the same version isn't sent twice.

## Acceptance criteria

- [ ] Tests with a fake SMTP server (aiosmtpd or a mock).
- [ ] A `review` verdict blocks sending unless `--force`.
- [ ] Docs: a setup guide (approved sender, Kindle email, app password for Gmail/Outlook).

## Out of scope

USB transfer, the Send to Kindle desktop app.
