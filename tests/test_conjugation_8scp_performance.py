"""Real-protein performance gate for the Conjugate Manager's initial site map.

Run explicitly after downloading the public RCSB fixture::

    curl -L https://files.rcsb.org/download/8SCP.pdb -o /tmp/8SCP.pdb
    .venv/bin/pytest -q tests/test_conjugation_8scp_performance.py
"""

from pathlib import Path
from time import perf_counter

import pytest

from backend.core.conjugation import find_conjugation_candidates
from backend.core.protein import parse_protein_pdb


@pytest.mark.integration
def test_8scp_initial_surface_mapping_completes_below_two_seconds():
    fixture = Path("/tmp/8SCP.pdb")
    if not fixture.is_file():
        pytest.skip("download https://files.rcsb.org/download/8SCP.pdb to /tmp/8SCP.pdb")

    asset = parse_protein_pdb(fixture.read_text(), name="8SCP")
    started = perf_counter()
    candidates = find_conjugation_candidates(asset)
    elapsed = perf_counter() - started

    # Pin the current RCSB structure census enough to catch a bad/partial fixture,
    # while allowing harmless upstream metadata changes outside the coordinate model.
    assert len(asset.atoms) >= 10_000
    assert len(candidates) == 70
    assert elapsed < 2.0, f"8SCP surface mapping took {elapsed:.3f}s"
    assert [item["accessible"] for item in candidates] == sorted(
        (item["accessible"] for item in candidates), reverse=True
    )
