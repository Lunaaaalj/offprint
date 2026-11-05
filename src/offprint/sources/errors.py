"""Errors raised by the resolver. Their messages are written for the person at the terminal."""


class SourceError(Exception):
    """Base class for everything the resolver raises on purpose."""


class InputError(SourceError, ValueError):
    """The INPUT isn't a DOI, an arXiv id, a supported URL or a supported file name."""


class ConfigError(SourceError, ValueError):
    """The configuration can't be used."""


class CacheError(SourceError):
    """A cache entry exists but can't be trusted."""


class NotResolvedError(SourceError):
    """Offline lookup found nothing: the input hasn't been resolved, or the file doesn't exist."""


class FetchError(SourceError):
    """One request failed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
