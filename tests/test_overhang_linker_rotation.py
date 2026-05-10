"""Regression: a non-identity OverhangSpec.rotation must be honoured by the
linker pipeline so that the linker's complement nucleotides on the OH helix
follow the rotated overhang frame.

Bug 2 (refactor_prompts/06): the user rotated an overhang in the 3D view, then
generated a linker between the rotated OH and another. The linker's complement
domain was rendered at the *un-rotated* overhang location. The OH itself
visually rotates because ``apply_overhang_rotation_if_needed`` rotates only the
OH domain's own nucleotides (mask = same helix, OH bp range, OH direction). The
linker's complement domain shares the same helix and bp range but with the
*opposite* direction, so the mask excludes it; the bridge anchor (looked up by
``_emit_bridge_nucs._anchor_for`` on the complement) ends up at the un-rotated
position and the bridge / connector arc visualises the un-rotated frame.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
)
from backend.api.routes import _demo_design


client = TestClient(app)


def _seed_with_real_oh_domains() -> Design:
    """Two extruded overhang helices, one staple per side. Mirrors the fixture
    from test_overhang_connections.py but kept local to keep this test
    self-contained."""
    base = _demo_design()
    oh_helix_a = Helix(
        id="oh_helix_a",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
        grid_pos=(0, 0),
    )
    oh_helix_b = Helix(
        id="oh_helix_b",
        axis_start=Vec3(x=5.0, y=0.0, z=0.0),
        axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
        grid_pos=(0, 3),
    )
    oh_strand_a = Strand(
        id="oh_strand_a",
        domains=[Domain(
            helix_id="oh_helix_a", start_bp=0, end_bp=7,
            direction=Direction.FORWARD, overhang_id="oh_a_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    oh_strand_b = Strand(
        id="oh_strand_b",
        domains=[Domain(
            helix_id="oh_helix_b", start_bp=0, end_bp=7,
            direction=Direction.REVERSE, overhang_id="oh_b_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [
        OverhangSpec(id="oh_a_5p", helix_id="oh_helix_a", strand_id="oh_strand_a", label="OHA",
                     pivot=[2.5, 0.0, 0.0]),
        OverhangSpec(id="oh_b_5p", helix_id="oh_helix_b", strand_id="oh_strand_b", label="OHB",
                     pivot=[5.0, 0.0, 0.0]),
    ]
    return base.model_copy(update={
        "helices": [*base.helices, oh_helix_a, oh_helix_b],
        "strands": [*base.strands, oh_strand_a, oh_strand_b],
        "overhangs": overhangs,
    })


def _post_conn() -> dict:
    body = {
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    }
    r = client.post("/api/design/overhang-connections", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _get_geom() -> list[dict]:
    return client.get("/api/design/geometry").json()["nucleotides"]


def _patch_rotation(ovhg_id: str, quat: list[float]) -> None:
    r = client.patch(f"/api/design/overhang/{ovhg_id}", json={"rotation": quat})
    assert r.status_code == 200, r.text


def _quat_axis_angle(axis: tuple[float, float, float], angle_rad: float) -> list[float]:
    nx, ny, nz = axis
    s = math.sin(angle_rad / 2.0)
    return [nx * s, ny * s, nz * s, math.cos(angle_rad / 2.0)]


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_seed_with_real_oh_domains())
    yield
    design_state.set_design(_demo_design())


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


def test_oh_rotation_moves_oh_nuc_baseline():
    """Sanity: rotating an OH non-trivially must move its own backbone nuc.
    If this fails, the rotation pipeline itself is broken — Bug 2 reproduction
    requires this baseline to hold first."""
    design_state.set_design(_seed_with_real_oh_domains())
    pre = _get_geom()
    # Baseline OH backbone position at the OH's free tip (bp 7).
    oh_pre = _find_nuc(pre, strand_id="oh_strand_a", helix_id="oh_helix_a",
                       bp_index=0, direction="FORWARD")
    pos_pre = np.asarray(oh_pre["backbone_position"], dtype=float)

    # Rotate 90° about Y around pivot at (2.5, 0, 0).
    _patch_rotation("oh_a_5p", _quat_axis_angle((0.0, 1.0, 0.0), math.pi / 2))

    post = _get_geom()
    oh_post = _find_nuc(post, strand_id="oh_strand_a", helix_id="oh_helix_a",
                        bp_index=0, direction="FORWARD")
    pos_post = np.asarray(oh_post["backbone_position"], dtype=float)

    delta = float(np.linalg.norm(pos_post - pos_pre))
    assert delta > 0.5, (
        f"Rotation did not move the OH nuc (Δ={delta:.3f} nm). The rotation "
        f"pipeline is broken — investigate before chasing Bug 2."
    )


def test_linker_complement_follows_rotated_overhang():
    """After rotating the OH, the linker complement nucleotide on the OH helix
    at the OH's attach bp must move WITH the OH (Watson-Crick paired). Before
    the fix the complement stays at the un-rotated position because
    apply_overhang_rotation_if_needed masks by domain direction and the
    complement domain has the OPPOSITE direction."""
    design_state.set_design(_seed_with_real_oh_domains())
    conn = _post_conn()
    cid = conn["design"]["overhang_connections"][0]["id"]

    # Baseline geometry — record OH nuc and complement nuc at bp 7.
    pre = _get_geom()
    oh_pre = _find_nuc(pre, strand_id="oh_strand_a", helix_id="oh_helix_a",
                       bp_index=0, direction="FORWARD")
    comp_pre = _find_nuc(pre, strand_id=f"__lnk__{cid}__a", helix_id="oh_helix_a",
                         bp_index=0, direction="REVERSE")
    oh_pos_pre   = np.asarray(oh_pre["backbone_position"],   dtype=float)
    comp_pos_pre = np.asarray(comp_pre["backbone_position"], dtype=float)

    # Rotate the OH 90° around Y at the pivot (2.5, 0, 0).
    _patch_rotation("oh_a_5p", _quat_axis_angle((0.0, 1.0, 0.0), math.pi / 2))

    post = _get_geom()
    oh_post = _find_nuc(post, strand_id="oh_strand_a", helix_id="oh_helix_a",
                        bp_index=0, direction="FORWARD")
    comp_post = _find_nuc(post, strand_id=f"__lnk__{cid}__a", helix_id="oh_helix_a",
                          bp_index=0, direction="REVERSE")
    oh_pos_post   = np.asarray(oh_post["backbone_position"],   dtype=float)
    comp_pos_post = np.asarray(comp_post["backbone_position"], dtype=float)

    oh_delta   = float(np.linalg.norm(oh_pos_post - oh_pos_pre))
    comp_delta = float(np.linalg.norm(comp_pos_post - comp_pos_pre))
    pair_pre   = float(np.linalg.norm(oh_pos_pre - comp_pos_pre))
    pair_post  = float(np.linalg.norm(oh_pos_post - comp_pos_post))

    # OH must move (sanity).
    assert oh_delta > 0.5, f"OH nuc did not move under rotation (Δ={oh_delta:.3f})"

    # Watson-Crick pairing distance must be preserved within a small tolerance.
    # Before the fix, the OH moves but the complement stays put — pair_post is
    # huge (≈ rotation amplitude) while pair_pre is small (~native bp distance).
    assert abs(pair_post - pair_pre) < 0.1, (
        f"Linker complement did not follow the rotated OH:\n"
        f"  OH moved Δ={oh_delta:.3f} nm; complement moved Δ={comp_delta:.3f} nm\n"
        f"  pair distance pre={pair_pre:.3f} nm; post={pair_post:.3f} nm — "
        f"complement lagged behind the OH"
    )


def test_design_round_trip_preserves_overhang_rotation():
    """A non-identity OverhangSpec.rotation survives Design.model_dump() +
    reload. This guards against losing the rotation field through a
    serialisation round-trip (the user's session can hit this on save/load)."""
    design_state.set_design(_seed_with_real_oh_domains())
    quat = _quat_axis_angle((0.0, 1.0, 0.0), math.pi / 2)
    _patch_rotation("oh_a_5p", quat)
    d = design_state.get_or_404()
    payload = d.model_dump(mode="json")
    restored = Design.model_validate(payload)
    rot = next(o.rotation for o in restored.overhangs if o.id == "oh_a_5p")
    assert all(abs(rot[i] - quat[i]) < 1e-9 for i in range(4)), (
        f"rotation lost in round-trip: stored={quat}, restored={rot}"
    )
