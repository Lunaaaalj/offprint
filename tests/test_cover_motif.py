"""The motif is stable for a paper, across processes, and stays clear of the text."""

import os
import re
import subprocess
import sys

import pytest

from offprint.cover.motif import BOTTOM, LEFT, RIGHT, TOP, motif_seed, network_svg
from offprint.ir import Meta

SEED_SCRIPT = """
from offprint.cover.motif import motif_seed
from offprint.ir import Meta
print(motif_seed(Meta(title="T", doi="10.3389/frai.2026.1748985")))
"""


def test_the_seed_survives_python_hash_randomisation() -> None:
    seeds = {
        subprocess.run(
            [sys.executable, "-c", SEED_SCRIPT],
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for hash_seed in ("1", "2")
    }

    assert len(seeds) == 1


def test_the_seed_is_pinned_so_a_change_of_scheme_is_deliberate() -> None:
    assert motif_seed(Meta(title="T", doi="10.3389/frai.2026.1748985")) == 18178336621615128047


@pytest.mark.parametrize(
    "doi", ["10.1234/ABC", "doi:10.1234/abc", "https://doi.org/10.1234/abc", " 10.1234/abc "]
)
def test_one_doi_is_one_seed_however_it_is_written(doi: str) -> None:
    assert motif_seed(Meta(title="T", doi=doi)) == motif_seed(Meta(title="U", doi="10.1234/abc"))


def test_papers_without_a_doi_fall_back_to_other_identifiers() -> None:
    by_arxiv = motif_seed(Meta(title="T", arxiv_id="2401.00001"))
    by_title = motif_seed(Meta(title="T"))

    assert by_arxiv != by_title


def test_different_papers_get_different_motifs() -> None:
    first = network_svg(motif_seed(Meta(title="T", doi="10.1/a")), has_hero=True)
    second = network_svg(motif_seed(Meta(title="T", doi="10.1/b")), has_hero=True)

    assert first != second


def test_the_same_seed_draws_the_same_motif() -> None:
    assert network_svg(7, has_hero=False) == network_svg(7, has_hero=False)


@pytest.mark.parametrize("has_hero", [True, False])
@pytest.mark.parametrize("seed", range(20))
def test_nodes_stay_clear_of_the_text(seed: int, has_hero: bool) -> None:
    svg = network_svg(seed, has_hero=has_hero)
    nodes = re.findall(r'cx="(\d+)" cy="(\d+)"', svg)

    assert nodes
    assert all(LEFT <= int(x) <= RIGHT and TOP <= int(y) <= BOTTOM for x, y in nodes)


def test_without_a_hero_the_motif_is_denser() -> None:
    assert network_svg(7, has_hero=False).count("<circle") > network_svg(7, has_hero=True).count(
        "<circle"
    )
