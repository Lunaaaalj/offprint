"""The email that carries a book to the Kindle."""

from email.message import EmailMessage


def build_message(data: bytes, *, filename: str, sender: str, to: str, title: str) -> EmailMessage:
    """An email with the EPUB attached. Amazon ignores the subject and body, so they are short."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = " ".join(title.split()) or filename
    message.set_content(f"{filename}, sent by offprint.")
    message.add_attachment(data, maintype="application", subtype="epub+zip", filename=filename)
    return message
