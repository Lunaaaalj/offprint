# Sending books to your Kindle

`offprint send book.epub` and `offprint convert … --send` email a finished EPUB to your Send-to-Kindle address. Only a book whose QA verdict is `pass` goes out by itself (see [`qa.md`](qa.md)).

Delivery is a separate stage. `convert` never uses the network unless you pass `--send`.

## One-time setup

### 1. Find your Kindle address

In Amazon's *Manage Your Content and Devices* → *Preferences* → *Personal Document Settings*, copy the **Send-to-Kindle E-Mail Address** of your device or app, such as `name_abc123@kindle.com`.

### 2. Approve the sender

On the same page, under **Approved Personal Document E-mail List**, add the address you will send *from*. Amazon drops mail from any other sender without telling you. That address is `sender` in the config.

### 3. SMTP access

offprint sends through your own mail account. Gmail and Outlook don't accept your normal password for this: create an **app password** (needs two-step verification).

| Account | SMTP host | Port | `security` | App password |
|---|---|---|---|---|
| Gmail | `smtp.gmail.com` | 587 | `starttls` | Google Account → Security → 2-Step Verification → App passwords |
| Outlook / Microsoft 365 | `smtp-mail.outlook.com` | 587 | `starttls` | Microsoft account → Security → Advanced security options → App passwords |

Some providers have changed or switched off basic SMTP login for personal accounts. If the login fails, check the provider's current SMTP settings.

### 4. The config file

`~/.config/offprint/config.toml` (`OFFPRINT_CONFIG_FILE` changes the path):

```toml
[kindle]
address = "name_abc123@kindle.com"
sender = "me@gmail.com"              # the approved sender

[smtp]
host = "smtp.gmail.com"
port = 587                           # optional: 587 starttls, 465 ssl, 25 none
security = "starttls"                # "starttls" (default), "ssl" or "none"
username = "me@gmail.com"            # leave out if the server needs no login

[limits]                             # optional
max_mb = 50
widths = [1600, 1200, 900, 600]
```

The password is **never** in this file, and offprint refuses a file that has one. It comes from:

1. the `OFFPRINT_SMTP_PASSWORD` environment variable, or
2. the OS keychain: `uv run keyring set offprint me@gmail.com`.

## Using it

```sh
offprint convert paper.pdf -o build/ --send     # convert, check, and send if it passed
offprint send build/paper.epub                  # send a book you already have
offprint send build/paper.epub --dry-run        # write build/paper.eml, send nothing
```

| Option | Effect |
|---|---|
| `--dry-run` | Writes `<stem>.eml` next to the book instead of connecting. It still checks the verdict, the duplicate log and the size, and it needs the config file but no password. |
| `--force` | Sends a book in `review`, or one that was already sent. |
| `--qa QA_JSON` | (`send` only) The QA report to read the verdict from. Default: `<stem>.qa.json` next to the book. |

**The verdict gate.** A book with verdict `review` isn't sent, and the command exits 3, as `convert` does. `send` reads the verdict from the `.qa.json` that `convert` wrote; a book with no report counts as not passed.
`convert --send --allow-review` exits 0 for a book in review but still doesn't send it; only `--force` does.

**Exit codes.** 0 sent or dry run, 1 it couldn't be sent (a message says why), 3 the verdict blocked it, 2 a usage error.

## Size limit

Amazon accepts up to **50 MB** per email. Its help pages disagree on whether that is per email or per attachment ([Send to Kindle by email](https://www.amazon.com/sendtokindle/email), [troubleshooting](https://www.amazon.com/gp/help/customer/display.html?nodeId=G5WYD9SAF7PGXRNA)), so offprint applies it to the whole encoded email, the stricter reading. Base64 makes the email a third larger than the EPUB, so the practical limit on the file is about 37 MB. Your mail provider may have a lower limit of its own (Gmail's is 25 MB).

When a book is over the limit, offprint downscales the PNG and JPEG images inside it to each width in `widths` in turn, largest first, and sends the first version that fits. The book on disk isn't changed. If it still doesn't fit at the smallest width, nothing is sent and the error says by how much. Set `max_mb` to a lower number if your provider needs it.

## The delivery log

Every attempt is appended to `~/.local/share/offprint/deliveries.jsonl` (`XDG_DATA_HOME` moves it, `OFFPRINT_DELIVERY_LOG` names the file):

```json
{"identifier": "arxiv:2611.09197", "sha256": "…", "time": "2026-11-09T18:00:00+00:00", "result": "sent", "to": "name_abc123@kindle.com"}
```

`sha256` is the hash of the EPUB on disk, before any downscaling. A book whose identifier and hash are already logged as `sent` isn't sent again without `--force`; a changed book is a new version. `result` is `sent` or `failed: ` and the reason, and a failure doesn't block a retry. Dry runs aren't logged.

## When a book doesn't arrive

- Check the Approved Personal Document E-mail List first. Amazon gives no error for an unapproved sender.
- Delivery takes a few minutes. The Kindle must be online and signed in to the same Amazon account.
- `--dry-run` and open the `.eml` to see exactly what would be sent.
