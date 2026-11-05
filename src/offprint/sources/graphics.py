"""Download a JATS article's figures from the PMC Open Access dataset. This is the networked part.

NCBI publishes each open-access article's files in a public S3 bucket, with a JSON record listing
them and their MD5 sums. Only names found in the article go through here, and only URLs inside the
article's own folder are fetched, so a hostile `xlink:href` can't point a request anywhere else.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from offprint.adapters.jats import JatsError, graphic_refs, parse_article, pmc_version
from offprint.sources import sniff
from offprint.sources.errors import FetchError
from offprint.sources.http import Http
from offprint.sources.model import Lookup

SERVICE = "PMC figures"
_BUCKET = "pmc-oa-opendata"
_BUCKET_URL = f"https://{_BUCKET}.s3.amazonaws.com"
_VERSION = re.compile(r"PMC\d+\.\d+")
_SHOWN_FAILURES = 5


@dataclass(frozen=True, slots=True)
class MediaFile:
    url: str
    md5: str


def record_url(version: str) -> str:
    return f"{_BUCKET_URL}/{quote(version, safe='')}/{quote(version, safe='')}.json"


def media_files(record: dict[str, Any], version: str) -> dict[str, MediaFile]:
    """Map file names to downloads, keeping only what's in this article's folder. Pure."""
    files: dict[str, MediaFile] = {}
    for url in record.get("media_urls") or ():
        parts = urlsplit(str(url))
        folder, _, name = parts.path.lstrip("/").rpartition("/")
        digest = parse_qs(parts.query).get("md5", [""])[0]
        if (parts.scheme, parts.netloc, folder) == ("s3", _BUCKET, version) and name and digest:
            files[name] = MediaFile(f"{_BUCKET_URL}/{version}/{quote(name)}", digest)
    return files


def find_media(name: str, files: dict[str, MediaFile]) -> MediaFile | None:
    """Find an href's file. Older articles leave the extension out of their hrefs. Pure."""
    if name in files:
        return files[name]
    matches = [media for key, media in files.items() if key.rpartition(".")[0] == name]
    return matches[0] if len(matches) == 1 else None


def fetch_graphics(source: bytes, http: Http) -> tuple[dict[str, bytes], Lookup | None]:
    """Download what `source` refers to. Returns the files, by href, and how that went.

    A failure doesn't lose the source: the outcome goes in the report, and `convert` refuses to
    run on an article with a graphic missing.
    """
    try:
        article = parse_article(source)
    except JatsError as error:
        return {}, Lookup(SERVICE, "failed", f"can't read the article: {error}")
    refs = graphic_refs(article)
    if not refs.names and not refs.rejected:
        return {}, None
    failures = [f"{href!r} isn't a plain file name" for href in refs.rejected]
    total = len(refs.names) + len(refs.rejected)

    version = pmc_version(article)
    if version is None or _VERSION.fullmatch(version) is None:
        reason = f"0 of {total} fetched: the article has no PMC id to find them with"
        return {}, Lookup(SERVICE, "failed", reason)
    try:
        files = media_files(http.get_json(record_url(version)), version)
    except FetchError as error:
        return {}, Lookup(SERVICE, "failed", f"0 of {total} fetched: {error}")

    graphics: dict[str, bytes] = {}
    for name in refs.names:
        try:
            graphics[name] = _download(name, files, http)
        except FetchError as error:
            failures.append(f"{name}: {error}")
    return graphics, _outcome(len(graphics), total, failures)


def _download(name: str, files: dict[str, MediaFile], http: Http) -> bytes:
    media = find_media(name, files)
    if media is None:
        raise FetchError("not in the article's open-access files")
    body = http.get_bytes(media.url)
    if hashlib.md5(body, usedforsecurity=False).hexdigest() != media.md5:
        raise FetchError("the download doesn't match its MD5 sum")
    if not sniff.is_image(body):
        raise FetchError("the download isn't an image")
    return body


def _outcome(fetched: int, total: int, failures: list[str]) -> Lookup:
    if not failures:
        return Lookup(SERVICE, "ok", f"{fetched} of {total} fetched")
    shown = "; ".join(failures[:_SHOWN_FAILURES])
    more = len(failures) - _SHOWN_FAILURES
    suffix = f"; and {more} more" if more > 0 else ""
    return Lookup(SERVICE, "failed", f"{fetched} of {total} fetched: {shown}{suffix}")
