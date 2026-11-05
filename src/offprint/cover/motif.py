"""The network motif behind a cover, seeded so one paper always gets the same one."""

import hashlib
import math
import random

from offprint.ir import Meta

WIDTH, HEIGHT = 1600, 2560
CENTRE = (800, 960)
LEFT, RIGHT = 60, WIDTH - 60
TOP, BOTTOM = 230, 1560  # Clear of the kicker above and the title below.
MAX_EDGE = 260
ACCENT_EVERY = 9


def motif_seed(meta: Meta) -> int:
    """Derive a stable seed from the paper's identity; `hash()` changes with every process."""
    doi = (meta.doi or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    identity = doi or meta.arxiv_id or meta.title
    return int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")


def _on_page(angle: float, radius: float) -> tuple[float, float] | None:
    x = CENTRE[0] + radius * math.cos(angle) * 0.95
    y = CENTRE[1] + radius * math.sin(angle) * 1.05
    return (x, y) if LEFT < x < RIGHT and TOP < y < BOTTOM else None


def _around_hero(rng: random.Random) -> tuple[float, float] | None:
    """Place a node on a ring outside the hero, or sometimes crossing it."""
    angle = rng.uniform(0, 2 * math.pi)
    radius = rng.uniform(560, 760) if rng.random() < 0.75 else rng.uniform(380, 560)
    return _on_page(angle, radius)


def _filling_the_space(rng: random.Random) -> tuple[float, float] | None:
    """Place a node anywhere in the disc: without a hero, the motif is the picture."""
    return _on_page(rng.uniform(0, 2 * math.pi), 700 * math.sqrt(rng.random()))


def network_svg(seed: int, *, has_hero: bool) -> str:
    """Draw the motif as an inline SVG; `cover.css` colours it."""
    rng = random.Random(seed)
    place, count, neighbours = (_around_hero, 70, 2) if has_hero else (_filling_the_space, 170, 3)
    nodes = [node for _ in range(count) if (node := place(rng)) is not None]

    edges: set[tuple[int, int]] = set()
    for i, node in enumerate(nodes):
        nearest = sorted((math.dist(node, other), j) for j, other in enumerate(nodes) if j != i)
        for distance, j in nearest[:neighbours]:
            if distance < MAX_EDGE:
                edges.add((min(i, j), max(i, j)))

    lines = "".join(
        f'<line x1="{nodes[i][0]:.0f}" y1="{nodes[i][1]:.0f}" '
        f'x2="{nodes[j][0]:.0f}" y2="{nodes[j][1]:.0f}"/>'
        for i, j in sorted(edges)
    )
    dots = "".join(
        f'<circle class="accent" cx="{x:.0f}" cy="{y:.0f}" r="9"/>'
        if k % ACCENT_EVERY == 0
        else f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.choice((4, 5, 6))}"/>'
        for k, (x, y) in enumerate(nodes)
    )
    return f'<svg class="motif" viewBox="0 0 {WIDTH} {HEIGHT}"><g>{lines}</g>{dots}</svg>'
