"""Two-channel lock on the atomistic display geometry.

``build_atomistic_model`` places every heavy atom from LOCKED, calibrated templates +
phase constants (CLAUDE.md: the ``_PHASE_*`` / atomistic frame constants must not drift
without approval), then closes the backbone across crossover and skip steps with an
L-BFGS-B bridge minimiser.  Those two halves need DIFFERENT oracles, which is why this
file has two channels.

**Channel 1 — the stamp (byte-exact).**  Every atom except the solver-placed bridges
comes straight out of the template stamp and IS bit-reproducible.  That is 98-99% of the
model, and hashing it catches drift in the per-atom placement, the phase constants, the
deformation pass, or the skip machinery — the things this lock exists for.

**Channel 2 — the bridges (tolerance).**  The ~5 atoms per junction that the minimiser
places — O3' of the outgoing residue plus P/OP1/OP2/O5' of the incoming one — are NOT
byte-reproducible across machines.  The bridge basin is near-flat, so a last-ULP
difference in a BLAS dot product walks the solver to a different converged point.
Measured at HEAD, same commit, same lockfile, same box: AVX-512 OpenBLAS kernels vs
``OPENBLAS_CORETYPE=Haswell`` move those atoms by up to 1.3 A (U6hb) / 0.7 A
(2hb_xover_val) while every other atom stays bit-identical.

That is why this file used to fail.  Four of its five goldens were CPU-dispatch
dependent, and the git history (77663ba -> 91a8eed -> 0cbbc9f -> 3093b83 -> ce1ef35)
is those goldens being "regenerated" and reverted in turn, because each of the two dev
machines read the other's values as a regression.  Thread count is NOT the variable —
1 vs N threads is byte-identical (see the note in conftest.py); kernel dispatch is.

The bridge's O3'-P LENGTH is far stabler than its position: the linker swings inside the
flat basin without stretching.  So channel 2 pins the SET of junctions exactly — that is
what changes when topology or the skip machinery moves — plus their bond lengths, banded
by whether the solve actually closed the step (see the tolerances below), and the mean
over all of them.

A channel-1 failure is a real geometry regression.  A channel-2 failure means the bridge
solve now converges somewhere else — also real, but a basin change rather than a
rounding change.  Regenerate both with::

    python -m tests.test_atomistic_geometry_lock --update
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model, atomistic_positions_flat

_EXAMPLES = Path(__file__).resolve().parent.parent / "Examples"
_BRIDGE_REF = Path(__file__).resolve().parent / "data" / "atomistic_bridge_lengths.json"

_NM_TO_A = 10.0

# Atoms of the incoming residue that the bridge solve places (plus the outgoing O3').
_BRIDGE_LINK = {"P", "OP1", "OP2", "O5'"}

# Channel-2 tolerances.  All three numbers are the measured worst case over the five
# designs on AVX-512 vs Haswell AND vs Nehalem kernels, which agree to the last digit.
#
# Junction lengths are strongly bimodal, with an empty gap at 3.17-3.48 A over all 925
# junctions.  Below it the bridge solve CLOSED the step and the length is a real (if
# strained, 2.3-2.7 A vs an ideal 1.60) phosphodiester bond, pinned by the solve and so
# reproducible to 1.7e-4 A.  Above it the solve left the step open — 4.9 A to 44 A, not a
# bond at any wavelength — and an unconstrained span floats with numerical noise, up to
# 0.213 A.  One tolerance for both bands would either be too loose to catch anything on
# the closed band or red on every cross-machine run on the open one.
_BRIDGE_BAND_A = 3.3          # in the measured empty gap
_BRIDGE_TOL_CLOSED_A = 0.01   # measured 0.00017 -> ~60x headroom
_BRIDGE_TOL_OPEN_A = 0.40     # measured 0.21321 -> ~1.9x headroom
#
# Mean over ALL junctions: kernel noise is unbiased and cancels, so the mean is far tighter
# than the per-junction tail (measured 0.0044 A).  A systematic shift in where the solve
# converges moves it; noise does not.  This is the sensitive half of channel 2.
_BRIDGE_MEAN_TOL_A = 0.02     # measured 0.00441 -> ~4.5x headroom

# Positions are nanometres (C1'-C2' reads 0.151, a 21 bp helix spans 7.35).


def _model(stem: str):
    design = Design.model_validate_json((_EXAMPLES / f"{stem}.nadoc").read_text())
    return build_atomistic_model(design, close_backbone=True, relaxed_oxdna_phase=True)


def _junction_key(o3) -> str:
    """Topological id of the residue a bridge leaves from.

    ``(helix_id, bp_index, direction)`` is one nucleotide — the same key the build itself
    uses for backbone bonds.  Extra-base / extension / copy indices are appended only when
    set, so designs that stack several residues on one lattice site stay unambiguous
    without changing the key for designs that don't.
    """
    extra = "".join(
        f":{tag}{value}"
        for tag, value in (("x", o3.extra_base_k), ("e", o3.ext_k), ("c", o3.copy_k))
        if value is not None
    )
    return f"{o3.helix_id}:{o3.bp_index}:{o3.direction}{extra}"


def _split(model) -> tuple[str, dict[str, float]]:
    """Partition the model into the byte-exact stamp and the solver-placed bridges.

    Returns ``(stamp_hash, {junction_key: O3'-P length in A})``.  A *junction* is a step
    between consecutive residues of one strand whose two residues are not adjacent bp on
    the same helix — a crossover or a skip, exactly the steps the bridge minimiser solves.

    This walks the STRAND (``strand_id`` + ``seq_num``), not ``model.bonds``.  At a skip
    the display emits no O3'-P bond at all — measured on U6hb, 41 skip junctions where
    ``O3'`` of bp 188 lists only its ``C3'`` neighbour while the next residue sits at bp
    190 — so a bond-walk is blind to precisely the junctions this file exists to cover,
    and leaves 205 solver-placed atoms inside the "byte-exact" hash.

    ``atomistic_positions_flat`` is indexed by atom SERIAL, which is not required to equal
    list order, so every index here is a serial.
    """
    flat = atomistic_positions_flat(model)          # 5 dp, nm — the display wire format
    xyz = np.asarray(flat, float).reshape(-1, 3)

    residues: dict[tuple[str, int], dict[str, int]] = {}
    lead: dict[tuple[str, int], object] = {}
    for atom in model.atoms:
        key = (atom.strand_id, atom.seq_num)
        residues.setdefault(key, {})[atom.name] = atom.serial
        lead.setdefault(key, atom)                  # all atoms of a residue share helix/bp

    bridge: set[int] = set()
    lengths: dict[str, float] = {}
    for key, out_res in lead.items():
        strand_id, seq_num = key
        in_res = lead.get((strand_id, seq_num + 1))
        if in_res is None:
            continue
        if out_res.helix_id == in_res.helix_id and abs(in_res.bp_index - out_res.bp_index) == 1:
            continue                                # ordinary intra-helix step: stamped
        o3 = residues[key].get("O3'")
        if o3 is None:
            continue
        # The solver places the outgoing O3' and the incoming P/OP1/OP2/O5'.
        incoming = residues[(strand_id, seq_num + 1)]
        bridge.add(o3)
        bridge.update(s for name, s in incoming.items() if name in _BRIDGE_LINK)
        p = incoming.get("P")
        if p is not None:
            lengths[_junction_key(out_res)] = round(
                float(np.linalg.norm(xyz[o3] - xyz[p])) * _NM_TO_A, 5
            )

    stamp = [flat[3 * s + axis]
             for s in range(len(xyz)) if s not in bridge
             for axis in range(3)]
    return hashlib.blake2b(json.dumps(stamp).encode(), digest_size=16).hexdigest(), lengths


def _reference() -> dict:
    return json.loads(_BRIDGE_REF.read_text())["designs"]


def _assert_bridges(stem: str, lengths: dict[str, float]) -> None:
    ref = _reference()[stem]
    added, removed = sorted(set(lengths) - set(ref)), sorted(set(ref) - set(lengths))
    assert not added and not removed, (
        f"{stem}: the set of solved junctions changed — added {added}, removed {removed}. "
        f"That is a topology/skip change, not solver noise."
    )
    deltas = {k: abs(lengths[k] - ref[k]) for k in ref}
    for closed in (True, False):
        band = {k: d for k, d in deltas.items()
                if (ref[k] <= _BRIDGE_BAND_A) is closed}
        if not band:
            continue
        tol = _BRIDGE_TOL_CLOSED_A if closed else _BRIDGE_TOL_OPEN_A
        worst_delta, worst_key = max((d, k) for k, d in band.items())
        assert worst_delta <= tol, (
            f"{stem}: {'closed' if closed else 'open'}-band junction {worst_key} O3'-P "
            f"length moved {worst_delta:.4f} A ({ref[worst_key]:.4f} -> "
            f"{lengths[worst_key]:.4f}), past the {tol} A tolerance. The bridge solve "
            f"converges somewhere new — a real change, not cross-machine rounding."
        )
    mean_delta = sum(deltas.values()) / len(deltas) if deltas else 0.0
    assert mean_delta <= _BRIDGE_MEAN_TOL_A, (
        f"{stem}: mean junction O3'-P length moved {mean_delta:.5f} A over "
        f"{len(deltas)} junctions, past the {_BRIDGE_MEAN_TOL_A} A tolerance. Kernel noise "
        f"is unbiased and cancels in the mean, so this is a systematic shift in the solve."
    )


# Fast: small crossover designs (<0.2 s each) — pin the per-atom stamp + the set and
# closure of the crossover bridges.
_FAST_GOLDEN = {
    "6hb_test":      "608b4720f69a3de9944863733ca10cdb",   # 2 crossover bridges
    "Con4":          "bdaccffedd48d2bd0a5c041191fb04a5",   # 3
    "2hb_xover_val": "4d1aa8ad7393943e06cd0031b6a3b709",   # 4
}

# Slow: large designs that additionally exercise the SKIP-site bridge and the
# deformation pass — the two paths most sensitive to any stamp perturbation.
_SLOW_GOLDEN = {
    "U6hb":                     "ac74058041002f76e6a394154d9abd4f",  # 353 bridges
    "multi_domain_test3_bend90": "d71be3c5a2c5e03d358ce654906593f5",  # 563 bridges
}


@pytest.mark.parametrize("stem,golden", sorted(_FAST_GOLDEN.items()))
def test_atomistic_stamp_is_byte_identical(stem, golden):
    stamp, _ = _split(_model(stem))
    assert stamp == golden, (
        f"{stem}: the stamped (non-bridge) atomistic geometry changed vs the locked "
        f"golden — {len(_FAST_GOLDEN)} designs share this stamp path, so suspect the "
        f"per-atom placement or the phase constants. If approved, regenerate."
    )


@pytest.mark.parametrize("stem", sorted(_FAST_GOLDEN))
def test_atomistic_crossover_bridges_match_reference(stem):
    _, lengths = _split(_model(stem))
    _assert_bridges(stem, lengths)


@pytest.mark.slow
@pytest.mark.parametrize("stem,golden", sorted(_SLOW_GOLDEN.items()))
def test_atomistic_stamp_skip_and_deformation_locked(stem, golden):
    stamp, _ = _split(_model(stem))
    assert stamp == golden, (
        f"{stem}: stamped skip/deformation atomistic geometry changed vs the golden."
    )


@pytest.mark.slow
@pytest.mark.parametrize("stem", sorted(_SLOW_GOLDEN))
def test_atomistic_skip_bridges_match_reference(stem):
    _, lengths = _split(_model(stem))
    _assert_bridges(stem, lengths)


if __name__ == "__main__":  # python -m tests.test_atomistic_geometry_lock --update
    import sys

    if "--update" not in sys.argv:
        print(__doc__)
        raise SystemExit(0)
    designs, hashes = {}, {}
    for _stem in list(_FAST_GOLDEN) + list(_SLOW_GOLDEN):
        _hash, _lengths = _split(_model(_stem))
        hashes[_stem] = _hash
        designs[_stem] = dict(sorted(_lengths.items()))
        print(f"{_stem:28s} stamp={_hash}  junctions={len(_lengths)}")
    _BRIDGE_REF.parent.mkdir(parents=True, exist_ok=True)
    _BRIDGE_REF.write_text(json.dumps({
        "__note__": (
            "Per-junction O3'-P phosphodiester bond lengths in ANGSTROM, keyed by the "
            "outgoing residue (helix_id:bp_index:direction). Channel 2 of "
            "tests/test_atomistic_geometry_lock.py — see that file's docstring for why "
            "the bridge atoms cannot be hashed byte-exactly across machines. "
            "Regenerate with: python -m tests.test_atomistic_geometry_lock --update"
        ),
        "designs": designs,
    }, indent=1, sort_keys=False) + "\n")
    print(f"\nwrote {_BRIDGE_REF}")
    print("\nPaste these into _FAST_GOLDEN / _SLOW_GOLDEN:")
    for _stem, _hash in hashes.items():
        print(f'    "{_stem}": "{_hash}",')
