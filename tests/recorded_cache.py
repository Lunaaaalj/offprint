"""A resolver cache seeded from recorded arXiv responses, for converting the NeurIPS fixture.

The fixture is arXiv 2611.09197, CC BY 4.0 on arXiv, and its PDF prints no licence (#60). These
helpers build the cache entry `offprint resolve` would leave, without the network.
"""

import json
from dataclasses import replace
from pathlib import Path

from offprint.ir import Meta
from offprint.sources import ArxivId, Resolution, arxiv, cache

RECORDING = Path(__file__).parent / "recordings" / "arxiv-neurips-metadata"
NEURIPS = ArxivId("2611.09197")


def recorded_meta() -> Meta:
    """arXiv's real record of the fixture, with the licence from its OAI-PMH response."""
    recording = json.loads((RECORDING / "exchanges.json").read_text(encoding="utf-8"))
    bodies = {item["url"]: RECORDING / item["body"] for item in recording["exchanges"]}
    [record] = arxiv.parse_feed(bodies[arxiv.query_url(NEURIPS)].read_bytes())
    license_ = arxiv.parse_oai_license(bodies[arxiv.oai_url(NEURIPS)].read_bytes())
    return replace(record.meta, license=license_, source_tier="latex")


def store(cache_dir: Path, meta: Meta | None, target: ArxivId = NEURIPS) -> None:
    """A cache entry as `resolve` leaves it. Its source file doesn't matter to a local convert."""
    resolution = Resolution(input=str(target), attempts=(), meta=meta, tier="pdf")
    cache.store(cache_dir, target, resolution, "source.pdf", b"%PDF-1.7 placeholder")
