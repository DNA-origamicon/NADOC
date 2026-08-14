"""Unified direct overhang connection (root-to-root + end-to-root, 2026-06-30).

Both direct types now materialize as ONE non-consuming OverhangBinding, relocated
on apply (duplex forms; driven tip↔root bond left stretched). Relax closes that
bond to ~0.67 nm. See backend/core/direct_relax.py + crud._cv_create_bound_binding.
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.crud import _geometry_for_design
from backend.api.routes_connection_versions import _cv_create_bound_binding
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.direct_relax import (
    _bead_pos,
    _find_driven_tip_and_root,
    relax_direct_binding,
)
from backend.core.models import (
    ClusterJoint,
    ClusterRigidTransform,
    Crossover,
    Direction,
    Domain,
    HalfCrossover,
    Helix,
    OverhangSpec,
    SubDomain,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.validator import validate_design

_IDENTITY = [0.0, 0.0, 0.0, 1.0]
_TARGET = 0.67
client = TestClient(app)


def _seed(*, same_body=False, cluster_b_translation=(5.0, 2.0, 1.0), joint=None):
    """Two extruded-style overhangs, each a [root → overhang-tip] staple."""
    base = _demo_design()
    L = 16
    ha = Helix(
        id="d_ha",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=L,
        grid_pos=(0, 0),
    )
    hb = Helix(
        id="d_hb",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=L,
        grid_pos=(0, 4),
    )
    sa = Strand(
        id="d_sa",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="d_ha", start_bp=0, end_bp=3, direction=Direction.FORWARD),
            Domain(
                helix_id="d_ha",
                start_bp=4,
                end_bp=11,
                direction=Direction.FORWARD,
                overhang_id="oh_a",
            ),
        ],
    )
    sb = Strand(
        id="d_sb",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="d_hb", start_bp=0, end_bp=3, direction=Direction.FORWARD),
            Domain(
                helix_id="d_hb",
                start_bp=4,
                end_bp=11,
                direction=Direction.FORWARD,
                overhang_id="oh_b",
            ),
        ],
    )
    overhangs = [
        OverhangSpec(
            id="oh_a",
            helix_id="d_ha",
            strand_id="d_sa",
            label="OHA",
            sequence="ACGTACGT",
        ),
        OverhangSpec(
            id="oh_b",
            helix_id="d_hb",
            strand_id="d_sb",
            label="OHB",
            sequence="ACGTACGT",
        ),
    ]
    if same_body:
        clusters = [
            ClusterRigidTransform(
                id="cAB",
                name="AB",
                helix_ids=["d_ha", "d_hb"],
                translation=[0, 0, 0],
                rotation=_IDENTITY,
                pivot=[0, 0, 0],
            )
        ]
    else:
        clusters = [
            ClusterRigidTransform(
                id="cA",
                name="A",
                helix_ids=["d_ha"],
                translation=[0, 0, 0],
                rotation=_IDENTITY,
                pivot=[0, 0, 0],
            ),
            ClusterRigidTransform(
                id="cB",
                name="B",
                helix_ids=["d_hb"],
                translation=list(cluster_b_translation),
                rotation=_IDENTITY,
                pivot=[0, 0, 0],
            ),
        ]
    return base.model_copy(
        update={
            "helices": [*base.helices, ha, hb],
            "strands": [*base.strands, sa, sb],
            "overhangs": overhangs,
            "cluster_transforms": clusters,
            "cluster_joints": [joint] if joint else [],
        }
    )


def _tip_root_chord(design) -> float:
    strand, _i, _td, _rd, cb_bp, cr_bp = _find_driven_tip_and_root(design, "oh_b")
    tip_dom = strand.domains[_i]
    root_dom = strand.domains[_i - 1 if _i == len(strand.domains) - 1 else _i + 1]
    nucs = _geometry_for_design(design)
    pb = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=cb_bp)
    pr = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=cr_bp)
    return float(np.linalg.norm(pb - pr))


def test_apply_direct_does_not_consume_and_relocates_root_to_root():
    d = _seed()
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    # Neither overhang consumed.
    assert {o.id for o in d.overhangs} == {"oh_a", "oh_b"}
    # One bound binding with the driver/driven recorded.
    assert len(d.overhang_bindings) == 1
    bnd = d.overhang_bindings[0]
    assert bnd.bound and bnd.driver_oh_id == "oh_a" and bnd.driven_oh_id == "oh_b"
    assert bnd.connection_type == "root-to-root"
    assert bnd.prior_driven_topology is not None
    # B's tip domain relocated onto A's helix (the duplex).
    sb = next(s for s in d.strands if s.id == "d_sb")
    tip = next(dm for dm in sb.domains if dm.overhang_id == "oh_b")
    assert tip.helix_id == "d_ha"
    # B's OverhangSpec.helix_id moved too.
    assert next(o for o in d.overhangs if o.id == "oh_b").helix_id == "d_ha"


def test_connection_version_apply_undo_redo_is_atomic_for_binding_and_duplex():
    """One Connect undo must clear every list entry created by the action.

    The display Duplex used to be POSTed after the snapshot-backed Apply, so it
    survived Undo even after the OverhangBinding was restored away.
    """
    design_state.close_session()
    seeded = _seed()
    seeded = seeded.model_copy(update={
        "overhangs": [
            o.model_copy(update={
                "sub_domains": [
                    SubDomain(id=f"sd_{o.id}", start_bp_offset=0, length_bp=8)
                ]
            })
            for o in seeded.overhangs
        ]
    })
    design_state.set_design(seeded)
    applied = client.post("/api/design/connection-versions/connect", json={
        "overhang_a_id": "oh_a",
        "overhang_b_id": "oh_b",
        "connection_type": "root-to-root",
        "overhang_a_seq": "ACGTACGT",
        "overhang_b_seq": "ACGTACGT",
    })
    assert applied.status_code == 201, applied.text
    live = design_state.get_or_404()
    assert len(live.overhang_bindings) == 1
    assert len(live.duplexes) == 1

    undone = client.post("/api/design/undo")
    assert undone.status_code == 200, undone.text
    live = design_state.get_or_404()
    assert live.overhang_bindings == []
    assert live.overhang_connections == []
    assert live.duplexes == []
    assert live.connection_versions == []

    redone = client.post("/api/design/redo")
    assert redone.status_code == 200, redone.text
    live = design_state.get_or_404()
    assert len(live.overhang_bindings) == 1
    assert len(live.duplexes) == 1


def _conn_bond(design, oh_id: str) -> float:
    """Length of the overhang↔embedded-staple (root) backbone bond for *oh_id* —
    the gap the duplex's connecting bead leaves to its root domain's connecting bp."""
    strand, _i, tip_dom, root_dom, c_bp, p_bp = _find_driven_tip_and_root(design, oh_id)
    nucs = _geometry_for_design(design)
    c = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=c_bp)
    p = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=p_bp)
    return float(np.linalg.norm(c - p))


def _conn_beads(design, oh_id):
    """(c, p) — duplex connecting bead and its embedded-staple root bead — as arrays."""
    strand, _i, tip_dom, root_dom, c_bp, p_bp = _find_driven_tip_and_root(design, oh_id)
    nucs = _geometry_for_design(design)
    c = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=c_bp)
    p = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=p_bp)
    return c, p


def test_apply_direct_seats_duplex_on_midpoint_symmetric_and_aligned():
    """NEW apply behavior (2026-07-01): the relocated duplex is re-seated like a linker
    bridge — ORIENTED along and CENTERED on the chord between its two embedded-staple
    connections — so the two root bonds share the stretch SYMMETRICALLY and the duplex
    axis is aligned with that chord (both bonds minimized), instead of the old one-sided
    placement (driver bond ~0.67, driven bond bearing the whole gap)."""
    from backend.core.duplex_cluster import duplex_cluster_for

    d = _seed(cluster_b_translation=(6.0, 3.0, 2.0))
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "free_end", "root", "end-to-root")
    # Pose now lives on the child DUPLEX cluster (not OverhangSpec) — non-trivial re-seat.
    cl = duplex_cluster_for(d, "oh_a")
    assert cl is not None and (
        np.linalg.norm(cl.translation) > 0.5 or cl.rotation != _IDENTITY
    )
    assert (
        next(o for o in d.overhangs if o.id == "oh_a").rotation == _IDENTITY
    )  # cleared
    c_a, p_a = _conn_beads(d, "oh_a")
    c_b, p_b = _conn_beads(d, "oh_b")
    # Symmetric split: both root bonds equal.
    bond_a, bond_b = np.linalg.norm(c_a - p_a), np.linalg.norm(c_b - p_b)
    assert abs(bond_a - bond_b) < 0.3, (bond_a, bond_b)
    assert bond_a > 1.0  # a real, shared stretch
    # Duplex connection axis aligned with the anchor chord (cos ≈ 1).
    u = c_b - c_a
    v = p_b - p_a
    cos = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))
    assert cos > 0.98, cos


def _ovhg_axis_endpoints(design, helix_id, ovhg_id):
    """Per-overhang axis (start, end) as arrays, after overhang rotation+translation."""
    from backend.core.deformation import (
        _apply_ovhg_rotations_to_axes,
        deformed_helix_axes,
    )

    nucs = _geometry_for_design(design)
    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucs)
    ax = next(a for a in axes if a["helix_id"] == helix_id)
    seg = ax["ovhg_axes"][ovhg_id]
    return np.asarray(seg["start"], float), np.asarray(seg["end"], float)


def test_apply_direct_moves_the_overhang_helix_axis_with_the_duplex():
    """Issue-1 regression: the driver overhang-helix AXIS line follows the re-seated
    duplex (via OverhangSpec.translation in _apply_ovhg_rotations_to_axes) instead of
    staying at the pre-apply lattice location, and its beads stay glued to the axis."""
    d = _seed(cluster_b_translation=(6.0, 3.0, 2.0))
    s0, e0 = _ovhg_axis_endpoints(d, "d_ha", "oh_a")
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    s1, e1 = _ovhg_axis_endpoints(d, "d_ha", "oh_a")
    # The overhang axis segment actually moved.
    assert np.linalg.norm(s1 - s0) > 0.5 or np.linalg.norm(e1 - e0) > 0.5, (
        s0,
        s1,
        e0,
        e1,
    )
    # Axis stays consistent with the transformed backbone bead (within a helix radius).
    c_a, _p_a = _conn_beads(d, "oh_a")
    dist_to_axis = min(np.linalg.norm(c_a - s1), np.linalg.norm(c_a - e1))
    assert dist_to_axis < 2.0, dist_to_axis


def test_unbind_removes_the_duplex_cluster():
    """Reverting the relocation drops the auto-created duplex CLUSTER (which carries the
    midpoint pose) and leaves the driver OverhangSpec identity — no stale pose/cluster."""
    from backend.core.binding_relax import revert_bind_topology
    from backend.core.duplex_cluster import duplex_cluster_for

    d = _seed(cluster_b_translation=(6.0, 3.0, 2.0))
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    cl = duplex_cluster_for(d, "oh_a")
    assert cl is not None and (
        np.linalg.norm(cl.translation) > 0.5 or cl.rotation != _IDENTITY
    )
    d = revert_bind_topology(d, d.overhang_bindings[0].prior_driven_topology)
    assert duplex_cluster_for(d, "oh_a") is None
    assert next(o for o in d.overhangs if o.id == "oh_a").rotation == _IDENTITY


def test_apply_direct_end_to_root_also_relocates_not_consumes():
    d = _seed()
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "free_end", "root", "end-to-root")
    assert {o.id for o in d.overhangs} == {"oh_a", "oh_b"}  # B not consumed
    assert d.overhang_bindings[0].connection_type == "end-to-root"
    # No ForcedLigation created (splice path is gone).
    assert d.forced_ligations == []


def test_relax_direct_closes_tip_root_chord_with_joint():
    joint = ClusterJoint(
        id="jB",
        cluster_id="cB",
        name="Hinge",
        local_axis_origin=[0.0, 0.0, 6 * BDNA_RISE_PER_BP],
        local_axis_direction=[0.0, 1.0, 0.0],
        min_angle_deg=-180.0,
        max_angle_deg=180.0,
    )
    d = _seed(cluster_b_translation=(6.0, 0.0, 0.0), joint=joint)
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    before = _tip_root_chord(d)
    # Apply already SEATS the duplex at the oriented midpoint; the bridge-method relax
    # rotates the joint to bring the two roots to the duplex's natural span, closing the
    # residual tip↔root bond to one backbone step. (A modest gap the single revolute can
    # reach; a very large gap only partially closes — the joint's reachability limit.)
    assert before > 0.85  # still stretched
    updated, info = relax_direct_binding(d, "oh_a", "oh_b")
    assert info["mode"] == "joints"
    after = _tip_root_chord(updated)
    assert after < before and after < 0.8, (before, after)
    # The duplex placement (re-seat + clash spin) now lives on the child DUPLEX cluster;
    # both OverhangSpec poses stay identity (pose migrated onto the cluster).
    from backend.core.duplex_cluster import duplex_cluster_for

    cl = duplex_cluster_for(updated, "oh_a")
    assert cl is not None and cl.rotation != _IDENTITY
    assert next(o for o in updated.overhangs if o.id == "oh_a").rotation == _IDENTITY
    assert next(o for o in updated.overhangs if o.id == "oh_b").rotation == _IDENTITY


def test_relax_logs_cluster_op_not_overhang_rotation_for_cluster_backed():
    """Feature-log follow-up: a cluster-backed relax logs a ClusterOpLogEntry for the
    DUPLEX cluster (stable id across relaxes) and NO overhang_rotation for the driver — so
    a timeline SEEK reconstructs the cluster pose instead of double-transforming the
    now-cleared OverhangSpec."""
    from backend.core.duplex_cluster import duplex_cluster_for

    joint = ClusterJoint(
        id="jB",
        cluster_id="cB",
        name="Hinge",
        local_axis_origin=[0.0, 0.0, 6 * BDNA_RISE_PER_BP],
        local_axis_direction=[0.0, 1.0, 0.0],
        min_angle_deg=-180.0,
        max_angle_deg=180.0,
    )
    d = _seed(cluster_b_translation=(6.0, 0.0, 0.0), joint=joint)
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    cl0 = duplex_cluster_for(d, "oh_a")
    assert cl0 is not None
    n_before = len(d.feature_log)
    updated, _info = relax_direct_binding(d, "oh_a", "oh_b")
    cl1 = duplex_cluster_for(updated, "oh_a")
    assert cl1 is not None and cl1.id == cl0.id  # stable id
    new_entries = updated.feature_log[n_before:]
    assert any(
        getattr(e, "feature_type", None) == "cluster_op"
        and getattr(e, "cluster_id", None) == cl1.id
        and getattr(e, "source", "") == "relax:duplex-cluster"
        for e in new_entries
    ), "no duplex-cluster cluster_op logged"
    assert not any(
        getattr(e, "feature_type", None) == "overhang_rotation"
        and "oh_a" in getattr(e, "overhang_ids", [])
        for e in new_entries
    ), "relax wrongly logged an overhang_rotation"
    # Re-relaxing keeps the SAME cluster id (idempotent id).
    upd2, _ = relax_direct_binding(updated, "oh_a", "oh_b")
    assert duplex_cluster_for(upd2, "oh_a").id == cl0.id


def _improper_msgs(design):
    return [
        r.message
        for r in validate_design(design).results
        if not r.ok and "Improper crossover" in r.message
    ]


def test_validator_flags_improper_crossover():
    """validate_design flags a crossover whose halves sit at MISMATCHED bp (an
    invalid lattice crossover — must be a forced ligation), and passes a valid one.
    This is the guard against the relocation drawing a line to the wrong overhang end."""
    d = _seed()
    good = Crossover(
        half_a=HalfCrossover(helix_id="d_ha", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="d_hb", index=5, strand=Direction.REVERSE),
    )
    assert not _improper_msgs(d.model_copy(update={"crossovers": [good]}))
    bad = Crossover(
        half_a=HalfCrossover(helix_id="d_ha", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="d_hb", index=9, strand=Direction.REVERSE),
    )
    assert _improper_msgs(d.model_copy(update={"crossovers": [bad]}))


def test_relax_direct_no_joint_translates_to_target():
    d = _seed(cluster_b_translation=(16.0, 8.0, 5.0))
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    before = _tip_root_chord(d)
    updated, info = relax_direct_binding(d, "oh_a", "oh_b")
    assert info["mode"] == "translate"
    after = _tip_root_chord(updated)
    assert before > 2.0 and abs(after - _TARGET) < 0.05, (before, after)


def test_unbind_then_rebind_roundtrips_same_body_unified_binding():
    """Bound-checkbox round-trip (Overhang Connections section) on a UNIFIED
    same-rigid-body root-to-root binding. Unbind (bound:false) reverts the
    relocation; the SECOND Bind (bound:true) must succeed — before the driver_side
    keystone it 422'd because compute_bind_topology's same-cluster guard fired
    (both overhangs on one body).
    """
    from fastapi.testclient import TestClient

    from backend.api import state as design_state
    from backend.api.main import app

    d = _seed(same_body=True)
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    bid = d.overhang_bindings[0].id
    design_state.set_design(d)
    client = TestClient(app)

    # Driven tip starts relocated onto the driver's helix.
    def _driven_tip_helix(design):
        sb = next(s for s in design.strands if s.id == "d_sb")
        return next(dm for dm in sb.domains if dm.overhang_id == "oh_b").helix_id

    assert _driven_tip_helix(design_state.get_or_404()) == "d_ha"

    # Unbind → relocation reverted (tip back on its own helix).
    r = client.patch(f"/api/design/overhang-bindings/{bid}", json={"bound": False})
    assert r.status_code == 200, r.text
    assert _driven_tip_helix(design_state.get_or_404()) == "d_hb"

    # Re-bind → relocation re-applied (would 422 without driver_side).
    r = client.patch(f"/api/design/overhang-bindings/{bid}", json={"bound": True})
    assert r.status_code == 200, r.text
    assert _driven_tip_helix(design_state.get_or_404()) == "d_ha"
