"""Regression: a non-identity OverhangSpec.rotation must co-rotate the overhang's
BINDING domain — for every binder kind, not just LINKER complements.

The user rotates an overhang via the "Edit Orientation" tool (writes
``OverhangSpec.rotation``, applied at geometry time by
``apply_overhang_rotation_if_needed``). Before this fix the rotation co-rotated
only LINKER complement domains; a hybridized binder stayed put, breaking the
Watson-Crick pairing visually.

Two binder kinds are pinned here, both keyed on ``Domain.binds_overhang_id``:

  1. A standalone **OH_BINDER** strand whose binding domain EXTENDS BEYOND the
     overhang's bp range on the same helix (a toehold from dragging the binder's
     free end). The whole domain — incl. the part past the overhang — must rotate
     rigidly. A control STAPLE (not a binder) must NOT move.
  2. An **end-to-root** binder spliced into a STAPLE strand
     (``apply_end_to_root_binder``). It is STAPLE-typed, so a strand-type filter
     would miss it; only the ``binds_overhang_id`` link identifies it. This is the
     case the old filter failed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import apply_end_to_root_binder
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
)


client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_geom() -> list[dict]:
    return client.get("/api/design/geometry").json()["nucleotides"]


def _patch_rotation(ovhg_id: str, quat: list[float]) -> None:
    r = client.patch(f"/api/design/overhang/{ovhg_id}", json={"rotation": quat})
    assert r.status_code == 200, r.text


def _quat_axis_angle(axis: tuple[float, float, float], angle_rad: float) -> list[float]:
    nx, ny, nz = axis
    s = math.sin(angle_rad / 2.0)
    return [nx * s, ny * s, nz * s, math.cos(angle_rad / 2.0)]


def _find_nuc(nucs, *, strand_id, helix_id, bp_index, direction=None):
    out = [n for n in nucs
           if n.get("strand_id") == strand_id
           and n.get("helix_id") == helix_id
           and n.get("bp_index") == bp_index
           and (direction is None or n.get("direction") == direction)]
    assert len(out) == 1, (
        f"expected exactly 1 nuc for {strand_id=} {helix_id=} {bp_index=} "
        f"{direction=}, got {len(out)}"
    )
    return out[0]


@pytest.fixture(autouse=True)
def _reset():
    yield
    design_state.set_design(_demo_design())


# ── Case 1: OH_BINDER strand with a toehold past the overhang ─────────────────

def _seed_oh_binder_with_toehold() -> Design:
    """Overhang A (bp 0-7 FORWARD) on its own helix + an OH_BINDER strand whose
    binding domain spans bp 0-10 REVERSE (3 bp past the overhang's free tip) on
    the SAME helix, plus a non-binder control STAPLE at bp 20-27 (excluded)."""
    base = _demo_design()
    oh_helix = Helix(
        id="oh_helix_a",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=30 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=30,
        grid_pos=(0, 0),
    )
    oh_strand = Strand(
        id="oh_strand_a",
        domains=[Domain(helix_id="oh_helix_a", start_bp=0, end_bp=7,
                        direction=Direction.FORWARD, overhang_id="oh_a")],
        strand_type=StrandType.STAPLE,
    )
    # Binder: antiparallel, bp 0-10 (REVERSE traversal 10→0), extends past OH (0-7).
    binder = Strand(
        id="binder_strand",
        domains=[Domain(helix_id="oh_helix_a", start_bp=10, end_bp=0,
                        direction=Direction.REVERSE, binds_overhang_id="oh_a")],
        strand_type=StrandType.OH_BINDER,
    )
    # Control: a non-binder STAPLE, same helix, antiparallel, but NON-overlapping
    # bp range — must be excluded by the relaxed partner filter.
    control = Strand(
        id="control_strand",
        domains=[Domain(helix_id="oh_helix_a", start_bp=27, end_bp=20,
                        direction=Direction.REVERSE)],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [OverhangSpec(id="oh_a", helix_id="oh_helix_a", strand_id="oh_strand_a",
                             label="OHA", pivot=[2.5, 0.0, 0.0])]
    return base.model_copy(update={
        "helices": [*base.helices, oh_helix],
        "strands": [*base.strands, oh_strand, binder, control],
        "overhangs": overhangs,
    })


def test_oh_binder_with_toehold_follows_rotated_overhang():
    design_state.set_design(_seed_oh_binder_with_toehold())
    pre = _get_geom()

    oh0_pre   = _find_nuc(pre, strand_id="oh_strand_a", helix_id="oh_helix_a", bp_index=0, direction="FORWARD")
    bind0_pre = _find_nuc(pre, strand_id="binder_strand", helix_id="oh_helix_a", bp_index=0, direction="REVERSE")
    bind10_pre = _find_nuc(pre, strand_id="binder_strand", helix_id="oh_helix_a", bp_index=10, direction="REVERSE")
    ctrl_pre  = _find_nuc(pre, strand_id="control_strand", helix_id="oh_helix_a", bp_index=20, direction="REVERSE")

    p_oh0_pre   = np.asarray(oh0_pre["backbone_position"], dtype=float)
    p_bind0_pre = np.asarray(bind0_pre["backbone_position"], dtype=float)
    p_bind10_pre = np.asarray(bind10_pre["backbone_position"], dtype=float)
    p_ctrl_pre  = np.asarray(ctrl_pre["backbone_position"], dtype=float)

    # Rotate the OH 90° about Y. Junction (pivot) is at A's 3' end (bp 7).
    _patch_rotation("oh_a", _quat_axis_angle((0.0, 1.0, 0.0), math.pi / 2))

    post = _get_geom()
    oh0_post   = _find_nuc(post, strand_id="oh_strand_a", helix_id="oh_helix_a", bp_index=0, direction="FORWARD")
    bind0_post = _find_nuc(post, strand_id="binder_strand", helix_id="oh_helix_a", bp_index=0, direction="REVERSE")
    bind10_post = _find_nuc(post, strand_id="binder_strand", helix_id="oh_helix_a", bp_index=10, direction="REVERSE")
    ctrl_post  = _find_nuc(post, strand_id="control_strand", helix_id="oh_helix_a", bp_index=20, direction="REVERSE")

    p_oh0_post   = np.asarray(oh0_post["backbone_position"], dtype=float)
    p_bind0_post = np.asarray(bind0_post["backbone_position"], dtype=float)
    p_bind10_post = np.asarray(bind10_post["backbone_position"], dtype=float)
    p_ctrl_post  = np.asarray(ctrl_post["backbone_position"], dtype=float)

    # OH moved (sanity).
    assert float(np.linalg.norm(p_oh0_post - p_oh0_pre)) > 0.5

    # In-overlap: WC pairing distance OH bp0 ↔ binder bp0 preserved.
    pair_pre  = float(np.linalg.norm(p_oh0_pre - p_bind0_pre))
    pair_post = float(np.linalg.norm(p_oh0_post - p_bind0_post))
    assert abs(pair_post - pair_pre) < 0.1, (
        f"binder bp0 lagged the OH: pair pre={pair_pre:.3f} post={pair_post:.3f}"
    )

    # Beyond-overhang (toehold) bp10 also moved, rigidly: distance to the pivot
    # (A's junction bead at bp 7) is preserved.
    assert float(np.linalg.norm(p_bind10_post - p_bind10_pre)) > 0.5, (
        "binder toehold bead (bp10, past the overhang) did NOT rotate with the OH"
    )
    pivot = np.asarray(_find_nuc(pre, strand_id="oh_strand_a", helix_id="oh_helix_a",
                                bp_index=7, direction="FORWARD")["backbone_position"], dtype=float)
    pivot_post = np.asarray(_find_nuc(post, strand_id="oh_strand_a", helix_id="oh_helix_a",
                                      bp_index=7, direction="FORWARD")["backbone_position"], dtype=float)
    r_pre  = float(np.linalg.norm(p_bind10_pre - pivot))
    r_post = float(np.linalg.norm(p_bind10_post - pivot_post))
    assert abs(r_post - r_pre) < 0.05, (
        f"toehold not rigid about pivot: |r| pre={r_pre:.3f} post={r_post:.3f}"
    )

    # Over-match guard: the non-binder control STAPLE did NOT move.
    assert float(np.linalg.norm(p_ctrl_post - p_ctrl_pre)) < 1e-6, (
        "non-binder control staple was swept by the overhang rotation"
    )


# ── Case 2: end-to-root binder spliced into a STAPLE strand ───────────────────

def _seed_end_to_root() -> tuple[Design, str, str]:
    """Overhang A (free) + overhang B as a 2-domain staple (root on the bundle
    helix + tip on B's own helix). Returns (design, a_id, b_id)."""
    base = _demo_design()
    oh_helix_a = Helix(id="oh_helix_a", axis_start=Vec3(x=2.5, y=0.0, z=0.0),
                       axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
                       phase_offset=0.0, length_bp=8, grid_pos=(0, 0))
    oh_helix_b = Helix(id="oh_helix_b", axis_start=Vec3(x=5.0, y=0.0, z=0.0),
                       axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
                       phase_offset=0.0, length_bp=8, grid_pos=(0, 3))
    oh_strand_a = Strand(
        id="oh_strand_a",
        domains=[Domain(helix_id="oh_helix_a", start_bp=0, end_bp=7,
                        direction=Direction.FORWARD, overhang_id="oh_a")],
        strand_type=StrandType.STAPLE,
    )
    # B: root domain anchored on the bundle helix, tip = the overhang on its own helix.
    oh_strand_b = Strand(
        id="oh_strand_b",
        domains=[
            Domain(helix_id="demo_helix", start_bp=20, end_bp=27, direction=Direction.REVERSE),
            Domain(helix_id="oh_helix_b", start_bp=0, end_bp=7,
                   direction=Direction.FORWARD, overhang_id="oh_b"),
        ],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [
        OverhangSpec(id="oh_a", helix_id="oh_helix_a", strand_id="oh_strand_a", label="OHA",
                     pivot=[2.5, 0.0, 0.0]),
        OverhangSpec(id="oh_b", helix_id="oh_helix_b", strand_id="oh_strand_b", label="OHB",
                     pivot=[5.0, 0.0, 0.0]),
    ]
    d = base.model_copy(update={
        "helices": [*base.helices, oh_helix_a, oh_helix_b],
        "strands": [*base.strands, oh_strand_a, oh_strand_b],
        "overhangs": overhangs,
    })
    return d, "oh_a", "oh_b"


def test_end_to_root_binder_follows_rotated_overhang():
    d, a_id, b_id = _seed_end_to_root()
    d = apply_end_to_root_binder(d, a_id, b_id)

    # Locate the spliced binder domain: a STAPLE-strand domain on A's helix tagged
    # binds_overhang_id == a_id.
    binders = [(s, di) for s in d.strands for di, dom in enumerate(s.domains)
               if dom.binds_overhang_id == a_id]
    assert len(binders) == 1, f"expected one end-to-root binder, got {len(binders)}"
    b_strand, b_di = binders[0]
    assert b_strand.strand_type == StrandType.STAPLE, "end-to-root binder must be STAPLE-typed"
    binder_dom = b_strand.domains[b_di]
    assert binder_dom.helix_id == "oh_helix_a"

    design_state.set_design(d)
    pre = _get_geom()
    oh0_pre   = _find_nuc(pre, strand_id="oh_strand_a", helix_id="oh_helix_a", bp_index=0, direction="FORWARD")
    bind0_pre = _find_nuc(pre, strand_id=b_strand.id, helix_id="oh_helix_a", bp_index=0,
                          direction=binder_dom.direction.value)
    p_oh0_pre   = np.asarray(oh0_pre["backbone_position"], dtype=float)
    p_bind0_pre = np.asarray(bind0_pre["backbone_position"], dtype=float)

    _patch_rotation(a_id, _quat_axis_angle((0.0, 1.0, 0.0), math.pi / 2))

    post = _get_geom()
    oh0_post   = _find_nuc(post, strand_id="oh_strand_a", helix_id="oh_helix_a", bp_index=0, direction="FORWARD")
    bind0_post = _find_nuc(post, strand_id=b_strand.id, helix_id="oh_helix_a", bp_index=0,
                           direction=binder_dom.direction.value)
    p_oh0_post   = np.asarray(oh0_post["backbone_position"], dtype=float)
    p_bind0_post = np.asarray(bind0_post["backbone_position"], dtype=float)

    # OH moved; the spliced STAPLE binder followed it (WC pairing preserved).
    assert float(np.linalg.norm(p_oh0_post - p_oh0_pre)) > 0.5, "OH did not move"
    pair_pre  = float(np.linalg.norm(p_oh0_pre - p_bind0_pre))
    pair_post = float(np.linalg.norm(p_oh0_post - p_bind0_post))
    assert abs(pair_post - pair_pre) < 0.1, (
        f"end-to-root binder lagged the rotated OH: pair pre={pair_pre:.3f} "
        f"post={pair_post:.3f} (the strand-type filter would fail here)"
    )
