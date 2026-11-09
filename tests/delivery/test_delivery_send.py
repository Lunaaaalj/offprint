"""Delivery: the gate, the size limit, the log, and a real SMTP round trip."""

import email
import json
import smtplib
import zipfile
from email import policy
from pathlib import Path

import pytest
from delivery_support import Inbox, free_port, noise_png

from offprint.delivery import DeliveryError, VerdictBlocked, deliver, read_verdict
from offprint.delivery.log import Record, already_sent, append
from offprint.delivery.message import build_message
from offprint.delivery.shrink import shrink_epub
from offprint.qa.book import read_book, read_package_meta


def attachment(raw: bytes) -> bytes:
    message = email.message_from_bytes(raw, policy=policy.default)
    (part,) = list(message.iter_attachments())
    return part.get_content()


def entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# The email


def test_the_message_carries_the_epub(epub: Path) -> None:
    message = build_message(
        epub.read_bytes(), filename="paper.epub", sender="a@b.co", to="k@kindle.com", title="T"
    )

    assert (message["From"], message["To"], message["Subject"]) == ("a@b.co", "k@kindle.com", "T")
    part = next(message.iter_attachments())
    assert part.get_content_type() == "application/epub+zip"
    assert part.get_filename() == "paper.epub"
    assert part.get_content() == epub.read_bytes()


def test_a_title_with_line_breaks_stays_a_single_header(epub: Path) -> None:
    title = read_package_meta(epub).title

    message = build_message(
        b"x", filename="p.epub", sender="a@b.co", to="k@kindle.com", title=title
    )

    assert message["Subject"] == "Safe Reinforcement Learning"


# The gate


@pytest.mark.parametrize("verdict", ["review", None])
def test_a_book_that_did_not_pass_is_blocked(epub, make_config, verdict) -> None:
    config = make_config()

    with pytest.raises(VerdictBlocked, match="--force"):
        deliver(epub, config, verdict=verdict, dry_run=True)

    assert not epub.with_suffix(".eml").exists()
    assert not config.log_path.exists()


def test_a_missing_report_is_called_unknown(epub, make_config) -> None:
    with pytest.raises(VerdictBlocked, match="unknown"):
        deliver(epub, make_config(), verdict=None, dry_run=True)


def test_force_sends_a_book_in_review(epub, make_config) -> None:
    done = deliver(epub, make_config(), verdict="review", force=True, dry_run=True)

    assert done.result == "dry-run"


def test_the_verdict_is_read_from_the_report_next_to_the_book(epub: Path) -> None:
    assert read_verdict(epub) is None
    epub.with_suffix(".qa.json").write_text('{"verdict": "pass"}', encoding="utf-8")

    assert read_verdict(epub) == "pass"


def test_the_report_can_be_somewhere_else(epub: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.json"
    other.write_text('{"verdict": "review"}', encoding="utf-8")

    assert read_verdict(epub, other) == "review"


def test_a_report_that_is_not_json_is_an_error(epub: Path) -> None:
    epub.with_suffix(".qa.json").write_text("not json", encoding="utf-8")

    with pytest.raises(DeliveryError, match="can't read the QA report"):
        read_verdict(epub)


# A dry run


def test_a_dry_run_writes_an_eml_and_sends_nothing(epub, make_config) -> None:
    config = make_config()

    done = deliver(epub, config, verdict="pass", dry_run=True)

    assert done.eml == epub.with_suffix(".eml")
    raw = done.eml.read_bytes()
    parsed = email.message_from_bytes(raw, policy=policy.default)
    assert (parsed["To"], parsed["From"]) == ("me_abc@kindle.com", "me@example.com")
    assert attachment(raw) == epub.read_bytes()
    assert not config.log_path.exists()


# Sending, with a real SMTP server


def test_the_book_arrives_and_is_logged(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)

    done = deliver(epub, config, verdict="pass")

    assert (done.result, done.to) == ("sent", "me_abc@kindle.com")
    (envelope,) = inbox.envelopes
    assert envelope.rcpt_tos == ["me_abc@kindle.com"]
    assert envelope.mail_from == "me@example.com"
    assert attachment(envelope.content) == epub.read_bytes()
    (record,) = entries(config.log_path)
    assert record["identifier"] == "arxiv:2611.09197"
    assert len(record["sha256"]) == 64
    assert (record["result"], record["to"]) == ("sent", "me_abc@kindle.com")


def test_the_same_version_is_not_sent_twice(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)
    deliver(epub, config, verdict="pass")

    with pytest.raises(DeliveryError, match="already sent"):
        deliver(epub, config, verdict="pass")

    assert len(inbox.envelopes) == 1


def test_force_sends_it_again(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)
    deliver(epub, config, verdict="pass")

    deliver(epub, config, verdict="pass", force=True)

    assert len(inbox.envelopes) == 2
    assert len(entries(config.log_path)) == 2


def test_a_changed_book_is_a_new_version(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)
    deliver(epub, config, verdict="pass")
    with zipfile.ZipFile(epub, "a") as archive:
        archive.writestr("OEBPS/extra.xhtml", "<p>more</p>")

    deliver(epub, config, verdict="pass")

    assert len(inbox.envelopes) == 2


def test_a_dry_run_also_reports_a_duplicate(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)
    deliver(epub, config, verdict="pass")

    with pytest.raises(DeliveryError, match="already sent"):
        deliver(epub, config, verdict="pass", dry_run=True)


def test_a_failed_send_is_logged_and_can_be_retried(epub, make_config) -> None:
    config = make_config(port=free_port())  # nothing listens here

    with pytest.raises(DeliveryError, match="wasn't sent"):
        deliver(epub, config, verdict="pass")

    (record,) = entries(config.log_path)
    assert record["result"].startswith("failed: ")
    assert already_sent(config.log_path, record["identifier"], record["sha256"]) is None


class StubSmtp:
    """Records what the sender does to an SMTP connection."""

    calls: list = []

    def __init__(self, config) -> None:
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def send_message(self, message) -> None:
        self.calls.append("send")


def test_starttls_then_login_then_send(epub, make_config) -> None:
    config = make_config(security="starttls", username="me@example.com")
    stub = StubSmtp(config)

    deliver(
        epub,
        config,
        verdict="pass",
        env={"OFFPRINT_SMTP_PASSWORD": "app-pw"},
        smtp_factory=lambda cfg: stub,
    )

    assert stub.calls == ["starttls", ("login", "me@example.com", "app-pw"), "send"]


def test_no_login_means_no_password_is_needed(epub, make_config) -> None:
    config = make_config(security="none", username=None)
    stub = StubSmtp(config)

    deliver(epub, config, verdict="pass", env={}, smtp_factory=lambda cfg: stub)

    assert stub.calls == ["send"]


def test_a_missing_password_stops_before_connecting(epub, make_config) -> None:
    config = make_config(username="me@example.com")

    def factory(cfg):
        raise AssertionError("shouldn't connect")

    with pytest.raises(DeliveryError, match="no SMTP password"):
        deliver(
            epub,
            config,
            verdict="pass",
            env={},
            smtp_factory=factory,
            keyring_get=lambda service, user: None,
        )

    assert not config.log_path.exists()


def test_a_server_that_refuses_the_message_is_a_delivery_error(epub, make_config) -> None:
    class Refusing(StubSmtp):
        def send_message(self, message) -> None:
            raise smtplib.SMTPRecipientsRefused({"x": (550, b"no")})

    config = make_config()

    with pytest.raises(DeliveryError, match="wasn't sent"):
        deliver(epub, config, verdict="pass", smtp_factory=lambda cfg: Refusing(cfg))

    assert entries(config.log_path)[0]["result"].startswith("failed")


# The size limit


def test_an_oversized_book_is_sent_with_smaller_images(big_epub, make_config, inbox: Inbox) -> None:
    config = make_config(
        host=inbox.host, port=inbox.port, max_bytes=2_000_000, widths=(1200, 800, 400)
    )

    done = deliver(big_epub, config, verdict="pass")

    assert done.shrunk_to in (1200, 800)
    assert done.message_bytes <= 2_000_000
    (envelope,) = inbox.envelopes
    sent = attachment(envelope.content)
    assert len(sent) < big_epub.stat().st_size
    assert zipfile.ZipFile(__import__("io").BytesIO(sent)).testzip() is None


def test_the_log_names_the_original_file(big_epub, make_config, inbox: Inbox) -> None:
    import hashlib

    config = make_config(host=inbox.host, port=inbox.port, max_bytes=2_000_000, widths=(800,))

    deliver(big_epub, config, verdict="pass")

    (record,) = entries(config.log_path)
    assert record["sha256"] == hashlib.sha256(big_epub.read_bytes()).hexdigest()
    with pytest.raises(DeliveryError, match="already sent"):
        deliver(big_epub, config, verdict="pass")


def test_a_book_under_the_limit_keeps_its_images(epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port)

    assert deliver(epub, config, verdict="pass").shrunk_to is None


def test_a_book_that_cannot_fit_is_not_sent(big_epub, make_config, inbox: Inbox) -> None:
    config = make_config(host=inbox.host, port=inbox.port, max_bytes=100_000, widths=(800, 400))

    with pytest.raises(DeliveryError, match=r"over the 0 MB limit.*downscaled to 400 px"):
        deliver(big_epub, config, verdict="pass")

    assert inbox.envelopes == []
    assert not config.log_path.exists()


# Shrinking an EPUB


def test_shrinking_keeps_the_epub_valid(big_epub: Path, tmp_path: Path) -> None:
    target = shrink_epub(big_epub, tmp_path / "small.epub", 400)

    with zipfile.ZipFile(target) as small, zipfile.ZipFile(big_epub) as big:
        assert small.namelist() == big.namelist()
        first = small.infolist()[0]
        assert (first.filename, first.compress_type) == ("mimetype", zipfile.ZIP_STORED)
        assert small.read("OEBPS/c.xhtml") == big.read("OEBPS/c.xhtml")
        assert small.getinfo("OEBPS/images/figure.png").file_size < (
            big.getinfo("OEBPS/images/figure.png").file_size / 3
        )
    assert read_book(target).spine == ("OEBPS/c.xhtml",)


def test_an_image_that_cannot_be_read_is_copied(tmp_path: Path) -> None:
    source = tmp_path / "bad.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OEBPS/broken.png", b"not an image")
        archive.writestr("OEBPS/ok.png", noise_png(900, 10))

    target = shrink_epub(source, tmp_path / "out.epub", 300)

    with zipfile.ZipFile(target) as out:
        assert out.read("OEBPS/broken.png") == b"not an image"
        assert len(out.read("OEBPS/ok.png")) < 900 * 10 * 3 / 2


def test_something_that_is_not_a_zip_is_a_delivery_error(tmp_path: Path) -> None:
    source = tmp_path / "x.epub"
    source.write_bytes(b"nope")

    with pytest.raises(DeliveryError, match="can't shrink"):
        shrink_epub(source, tmp_path / "y.epub", 100)


def test_a_file_that_is_not_an_epub_is_refused(tmp_path: Path, make_config) -> None:
    junk = tmp_path / "junk.epub"
    junk.write_bytes(b"nope")

    with pytest.raises(DeliveryError, match="can't read junk.epub as an EPUB"):
        deliver(junk, make_config(), verdict="pass", dry_run=True)


# The log


def test_the_log_ignores_a_damaged_line(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text('{"half": \n', encoding="utf-8")
    record = Record(identifier="i", sha256="h", time="t", result="sent", to="k@kindle.com")
    append(path, record)

    assert already_sent(path, "i", "h") == record
    assert already_sent(path, "i", "other") is None
    assert already_sent(path, "other", "h") is None


def test_a_missing_log_has_sent_nothing(tmp_path: Path) -> None:
    assert already_sent(tmp_path / "none.jsonl", "i", "h") is None
