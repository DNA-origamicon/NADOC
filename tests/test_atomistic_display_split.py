"""Golden parity test for the fast CG→atomistic display split.

The fast display path ships, per relaxed frame, only the per-nucleotide rigid frames
(origin + R) plus the small non-rigid atom set, and expands the fixed atom templates
client-side (`world = origin + R @ local`).  This test proves the reassembly reproduces
the authoritative `frame_atomistic_flat` (what the slow per-atom path draws) to a tight
tolerance, on designs that exercise crossovers, nicks, a loop insertion, and a bend
deformation (the G-fold path).

Tolerance-based (1e-4 nm), NOT byte-identical: the client expands in float32 and the
deformation fold re-associates the rotation at the ULP.  The byte-identical builder lock
(`test_atomistic_geometry_lock.py`) still guards the authoritative build unchanged.
"""
import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import (
    Design, LatticeType, StrandType, Direction, DeformationOp, BendParams,
)
from backend.core.design_geometry import _geometry_for_design
from backend.core.atomistic import atomistic_stamp_descriptor
from backend.core.oxdna_health import display_frames_payload, frame_atomistic_flat
from backend.physics.oxdna_interface import write_configuration, read_configuration_full

from tests.conftest import SIX_HB_CELLS


def _routed_6hb() -> Design:
    """Small routed 6hb (crossovers + auto-break nicks)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _routed_6hb_with_loop() -> Design:
    """Routed 6hb + a +1 loop insertion (extra loop-copy nucleotide)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404().model_copy(deep=True)
        h0 = d.helices[0]
        hb.loop_skip(h0.id, h0.bp_start + h0.length_bp // 2, +1)
        return design_state.get_or_404().model_copy(deep=True)


def _routed_6hb_bent() -> Design:
    """Routed 6hb + a bend DeformationOp (exercises the deformation/cluster G-fold)."""
    d = _routed_6hb()
    d = d.model_copy(update={"deformations": [DeformationOp(
        type="bend", plane_a_bp=8, plane_b_bp=34,
        affected_helix_ids=[h.id for h in d.helices],
        params=BendParams(curvature_deg_per_bp=1.5),
    )]})
    return d


def _frame_for(design: Design) -> dict:
    """A per-nucleotide frame {key: {backbone_position, a1, a3}} for the design — the
    seed configuration read back (parity only needs a consistent frame on both sides)."""
    geom = _geometry_for_design(design)
    import tempfile, os
    tf = tempfile.NamedTemporaryFile(suffix=".dat", delete=False).name
    try:
        write_configuration(design, geom, tf)
        return read_configuration_full(
            tf, design, copies=True, include_extra_bases=True, include_extensions=True)
    finally:
        os.unlink(tf)


def _reassemble(design: Design, frame: dict) -> np.ndarray:
    """Client-side expansion: rigid atoms via origin+R@local, non-rigid copied through."""
    desc = atomistic_stamp_descriptor(design)
    payload = display_frames_payload(design, frame)
    F = payload["frames"]
    n_atoms = len(desc.atom_nuc)
    flat = np.zeros(n_atoms * 3, dtype=float)
    for s in range(n_atoms):
        ni = desc.atom_nuc[s]
        if ni < 0:
            continue
        o = F[12 * ni:12 * ni + 3]
        R = F[12 * ni + 3:12 * ni + 12]           # row-major
        lx, ly, lz = desc.atom_local[s]
        flat[3 * s + 0] = o[0] + R[0] * lx + R[1] * ly + R[2] * lz
        flat[3 * s + 1] = o[1] + R[3] * lx + R[4] * ly + R[5] * lz
        flat[3 * s + 2] = o[2] + R[6] * lx + R[7] * ly + R[8] * lz
    nr = payload["nonrigid_xyz"]
    for j, s in enumerate(desc.nonrigid_serials):
        flat[3 * s:3 * s + 3] = nr[3 * j:3 * j + 3]
    return flat


@pytest.mark.parametrize("builder", [_routed_6hb, _routed_6hb_with_loop, _routed_6hb_bent],
                         ids=["routed", "loop_insertion", "bent"])
def test_split_reproduces_frame_atomistic_flat(builder):
    design = builder()
    frame = _frame_for(design)

    ref = np.asarray(frame_atomistic_flat(design, frame), dtype=float)
    got = _reassemble(design, frame)

    assert got.shape == ref.shape, f"atom-count mismatch {got.shape} vs {ref.shape}"
    max_dev = float(np.max(np.abs(got - ref))) if ref.size else 0.0
    assert max_dev < 1e-4, f"max |Δ| = {max_dev:.2e} nm exceeds 1e-4 (split diverged from authoritative build)"


def test_descriptor_nonrigid_set_is_override_stable():
    """The non-rigid SET is topology-determined, so populating the frame's override maps
    (positions) must not change WHICH serials are non-rigid — only their coordinates."""
    design = _routed_6hb_with_loop()
    desc = atomistic_stamp_descriptor(design)
    # display_frames_payload runs the build WITH overrides; its non-rigid indices come
    # straight from desc.nonrigid_serials, so a successful parity run above already relies
    # on this. Here we assert the descriptor is deterministic + cached identically.
    desc2 = atomistic_stamp_descriptor(design)
    assert desc2 is desc                              # cache hit → same object
    assert len(desc.nonrigid_serials) == len(set(desc.nonrigid_serials))
    assert all(desc.atom_nuc[s] == -1 for s in desc.nonrigid_serials)
