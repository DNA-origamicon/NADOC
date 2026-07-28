"""Byte-for-byte lock on the atomistic display geometry.

`build_atomistic_model` places every heavy atom from LOCKED, calibrated templates
+ phase constants (CLAUDE.md: the `_PHASE_*` / atomistic frame constants must not
drift without approval) and then refines the backbone with an L-BFGS-B bridge
minimiser.  That minimiser has near-degenerate minima, so even a last-ULP change
to the per-atom stamp (e.g. replacing `origin + R @ local` with a batched
`local_stack @ R.T` matmul) amplifies into ~0.1-0.8 A geometry swings at
crossover/skip junctions — a real change the /validate-atomistic audit would see.

These goldens are the hash of the rounded flat-XYZ (`atomistic_positions_flat`,
5 dp — the exact display wire format) captured from the reviewed geometry.  A
failure means the reconstructed geometry moved; if that was an APPROVED change,
regenerate the hashes (see `_hash_of`), otherwise it's an accidental regression.
"""
import hashlib
import json
from pathlib import Path

import pytest

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model, atomistic_positions_flat

_EXAMPLES = Path(__file__).resolve().parent.parent / "Examples"


def _hash_of(stem: str) -> str:
    d = Design.model_validate_json((_EXAMPLES / f"{stem}.nadoc").read_text())
    flat = atomistic_positions_flat(
        build_atomistic_model(d, close_backbone=True, relaxed_oxdna_phase=True)
    )
    return hashlib.blake2b(json.dumps(flat).encode(), digest_size=16).hexdigest()


# Fast: small crossover designs (<0.2 s each) — pin the per-atom stamp + the
# crossover backbone-bridge minimiser.
_FAST_GOLDEN = {
    "6hb_test":      "f8667c3808b7a38a6214cdd317c80e11",
    # Regenerated 2026-07-16: the committed 4 fs extra-base geometry work (c240eef / 742c19b)
    # deterministically shifted the crossover backbone-bridge minimiser for these two designs;
    # the goldens were never updated in those commits.  6hb_test is unchanged, confirming this
    # is a design-specific geometry change, not wholesale stamp/platform drift.
    # Regenerated again 2026-07-18: commit 91a8eed (phosphate 4fs-safe on position-only override
    # inserts) shifted the same two extra-base designs without updating the goldens.  6hb_test
    # (no such inserts) still matches, again confirming a design-specific change, not drift.
    # Regenerated again 2026-07-28: commit d9bed33 (crossover extra bases were built topologically
    # CATENATED) necessarily re-places the inserted bases, shifting these two without updating the
    # goldens.  APPROVED — verified by the fix's own oracle rather than by pattern-match:
    # `scripts/check_catenation.py` now reports catenated=0 for Con4 (1 reciprocal junction) and
    # 2hb_xover_val (2).  6hb_test has 0 reciprocal extra-base junctions and its hash is unchanged,
    # which is exactly why it is the drift control.
    "Con4":          "1c2f22b9d164e88add0ade366ae5e416",
    "2hb_xover_val": "77b38f80cde66f179fb03b2ff88f35ba",
}

# Slow: large designs that additionally exercise the SKIP-site bridge and the
# deformation pass — the two paths most sensitive to any stamp perturbation.
_SLOW_GOLDEN = {
    "U6hb":                     "66372728af0823bf1ca6ac463fe29494",  # 240 xovers + 72 skips
    "multi_domain_test3_bend90": "ad739cf58225d12dcf1b8304187b35ff", # 216 skips + bend deformation
}


@pytest.mark.parametrize("stem,golden", sorted(_FAST_GOLDEN.items()))
def test_atomistic_geometry_is_byte_identical(stem, golden):
    assert _hash_of(stem) == golden, (
        f"{stem}: atomistic display geometry changed vs the locked golden. "
        f"If this was an approved geometry change, regenerate the hash."
    )


@pytest.mark.slow
@pytest.mark.parametrize("stem,golden", sorted(_SLOW_GOLDEN.items()))
def test_atomistic_geometry_skip_and_deformation_locked(stem, golden):
    assert _hash_of(stem) == golden, (
        f"{stem}: skip/deformation atomistic geometry changed vs the locked golden."
    )
