"""Source resolver: from a DOI, arXiv id or file to the best available source (#9).

`resolve` is the networked stage: it looks the paper up and caches the best source.
`cached_source` is the offline counterpart for `convert`: it never touches the network.
"""

from offprint.sources.config import Config, load_config
from offprint.sources.errors import (
    CacheError,
    ConfigError,
    FetchError,
    InputError,
    NotResolvedError,
    SourceError,
)
from offprint.sources.identify import ArxivId, Doi, LocalFile, SourceInput, detect_input
from offprint.sources.model import Attempt, Lookup, Resolution
from offprint.sources.report import format_report
from offprint.sources.resolver import cached_source, merge_meta, resolve

__all__ = [
    "ArxivId",
    "Attempt",
    "CacheError",
    "Config",
    "ConfigError",
    "Doi",
    "FetchError",
    "InputError",
    "LocalFile",
    "Lookup",
    "NotResolvedError",
    "Resolution",
    "SourceError",
    "SourceInput",
    "cached_source",
    "detect_input",
    "format_report",
    "load_config",
    "merge_meta",
    "resolve",
]
