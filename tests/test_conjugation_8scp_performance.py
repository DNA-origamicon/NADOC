"""Real-protein performance gate over the committed, provenance-pinned 8SCP input."""

import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter

import pytest

from backend.core.conjugation import find_conjugation_candidates
from backend.core.protein import parse_protein_pdb


@pytest.mark.integration
def test_8scp_initial_surface_mapping_completes_below_two_seconds():
    fixtures = Path(__file__).parent / "fixtures"
    raw = gzip.decompress((fixtures / "8scp.pdb.gz").read_bytes())
    provenance = json.loads((fixtures / "8scp.provenance.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == provenance["uncompressed_sha256"]
    asset = parse_protein_pdb(raw.decode(), name="8SCP")
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
