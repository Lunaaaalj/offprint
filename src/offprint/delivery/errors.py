"""What can stop a delivery."""


class DeliveryError(Exception):
    """A book wasn't sent, and the message says why and what to do."""


class VerdictBlocked(DeliveryError):
    """The book's QA verdict isn't `pass`, and `--force` wasn't given."""
