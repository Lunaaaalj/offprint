"""The text `offprint resolve` prints. Pure."""

from offprint.sources.model import TIERS, Resolution


def format_report(resolution: Resolution) -> str:
    """Say what was found, what was chosen, and why each tier was or wasn't used."""
    lines = [f"input: {resolution.input}"]
    if resolution.meta is not None:
        lines.append(f"title: {resolution.meta.title}")
    if resolution.from_cache:
        lines.append("from the cache: no network used (--refresh looks everything up again)")

    if resolution.lookups:
        lines += ["", "metadata:"]
        for lookup in resolution.lookups:
            lines.append(f"  {lookup.service}: {lookup.status}: {lookup.reason}")

    for number, tier in enumerate(TIERS, start=1):
        lines += ["", f"tier {number} ({tier}):"]
        for attempt in resolution.attempts:
            if attempt.tier == tier:
                lines.append(f"  {attempt.source}: {attempt.status}: {attempt.reason}")
                if attempt.url:
                    lines.append(f"    {attempt.url}")

    lines.append("")
    if resolution.path is None:
        lines.append("choice: none: no source could be obtained")
    else:
        lines.append(f"choice: tier {TIERS.index(resolution.tier) + 1} ({resolution.tier})")
        lines.append(f"file: {resolution.path}")
        if _better_tier_failed(resolution):
            lines.append("warning: a better tier failed. Try again later with --refresh.")
    return "\n".join(lines)


def _better_tier_failed(resolution: Resolution) -> bool:
    assert resolution.tier is not None
    better = TIERS[: TIERS.index(resolution.tier)]
    return any(item.status == "failed" and item.tier in better for item in resolution.attempts)
