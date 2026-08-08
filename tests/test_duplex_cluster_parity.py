"""Phase 1 [[overhang-duplex-cluster]] — the WORLD-overlay → REST-child conjugation
reproduces the overhang pose geometry EXACTLY, so migrating the pose from
``OverhangSpec.rotation``/``translation`` onto a child ``ClusterRigidTransform`` is a
geometry-neutral switch. Exercised with a NON-identity parent cluster (the conjugation is
the identity map when the parent is identity, so that alone would prove nothing)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

# Untracked fixture with no headless builder yet (design-automation AF-FIXTURES); the one test
# below that reads it skips cleanly where it's absent (fresh checkout / other computer).
_REAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"

from backend.api.crud import _geometry_for_design
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.direct_relax import _overhang_root_pivot
from backend.core.duplex_cluster import (
    _duplex_domain_refs,
    _owning_parent_cluster,
    conjugate_world_pose_into_parent_rest,
)
from backend.core.models import (
    ClusterRigidTransform,
    Direction,
    Domain,
    Helix,
    OverhangSpec,
    Strand,
    StrandType,
    Vec3,
)


def _quat(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    h = math.radians(deg) / 2.0
    s = math.sin(h)
    return [float(a[0] * s), float(a[1] * s), float(a[2] * s), float(math.cos(h))]


def _seed(*, ovhg_rotation, ovhg_translation, parent):
    base = _demo_design()
    L = 16
    h = Helix(
        id="dc_h",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=L,
        grid_pos=(0, 0),
    )
    s = Strand(
        id="dc_s",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="dc_h", start_bp=0, end_bp=3, direction=Direction.FORWARD),
            Domain(
                helix_id="dc_h",
                start_bp=4,
                end_bp=11,
                direction=Direction.FORWARD,
                overhang_id="oh_a",
            ),
        ],
    )
    ov = OverhangSpec(
        id="oh_a",
        helix_id="dc_h",
        strand_id="dc_s",
        label="OHA",
        sequence="ACGTACGT",
        rotation=ovhg_rotation,
        translation=ovhg_translation,
    )
    return base.model_copy(
        update={
            "helices": [h],
            "strands": [s],
            "overhangs": [ov],
            "cluster_transforms": [parent],
        }
    )


def _ovhg_beads(nucs):
    return {
        n["bp_index"]: np.asarray(
            n.get("backbone_position") or n.get("base_position"), float
        )
        for n in nucs
        if n.get("overhang_id") == "oh_a"
    }


def test_conjugation_reproduces_overlay_geometry_with_nonidentity_parent():
    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["dc_h"],
        rotation=_quat([0.3, 1.0, 0.2], 33.0),
        translation=[4.0, -2.0, 1.5],
        pivot=[1.0, 0.5, 0.0],
    )
    r_w = _quat([0.0, 1.0, 0.0], 25.0)
    t_w = [0.0, 1.7, 0.3]

    # (1) Overlay path: OverhangSpec pose active, no duplex cluster.
    overlay = _seed(ovhg_rotation=r_w, ovhg_translation=t_w, parent=parent)
    overlay_nucs = _geometry_for_design(overlay)

    # pivot_world = the junction bead in the PARENT-posed but PRE-overlay frame
    # (T_P(junction_rest)) — read it off a pose-CLEARED copy, so the overlay's own
    # translation doesn't shift it.
    cleared = _seed(
        ovhg_rotation=[0, 0, 0, 1], ovhg_translation=[0, 0, 0], parent=parent
    )
    pivot_world = _overhang_root_pivot(cleared, _geometry_for_design(cleared), "oh_a")

    # (2) Child path: conjugate the overlay into the parent's rest frame, add the child
    #     cluster covering the overhang domain, and CLEAR the OverhangSpec pose.
    helix_id, refs = _duplex_domain_refs(overlay, "oh_a")
    par = _owning_parent_cluster(overlay, helix_id)
    q_c, piv_c, t_c = conjugate_world_pose_into_parent_rest(r_w, pivot_world, t_w, par)
    child = ClusterRigidTransform(
        id="C",
        name="Duplex 1",
        helix_ids=[helix_id],
        domain_ids=refs,
        parent_cluster_id=par.id,
        rotation=q_c,
        pivot=piv_c,
        translation=t_c,
    )
    cleared = cleared.model_copy(update={"cluster_transforms": [parent, child]})
    child_nucs = _geometry_for_design(cleared)

    a, b = _ovhg_beads(overlay_nucs), _ovhg_beads(child_nucs)
    assert set(a) == set(b) and a
    for bp in a:
        assert np.allclose(a[bp], b[bp], atol=1e-6), (bp, a[bp], b[bp])


def test_materialize_is_geometry_neutral_and_round_trips():
    """materialize_duplex_cluster moves the pose onto a child cluster with IDENTICAL
    geometry and clears the OverhangSpec pose; dematerialize restores both."""
    from backend.core.duplex_cluster import (
        materialize_duplex_cluster,
        dematerialize_duplex_cluster,
        duplex_cluster_for,
    )

    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["dc_h"],
        rotation=_quat([0.2, 1.0, 0.4], 41.0),
        translation=[-3.0, 5.0, 2.0],
        pivot=[0.5, 0.0, 1.0],
    )
    r_w = _quat([1.0, 0.3, 0.0], 22.0)
    t_w = [0.0, 1.2, 0.6]
    base = _seed(ovhg_rotation=r_w, ovhg_translation=t_w, parent=parent)
    base_beads = _ovhg_beads(_geometry_for_design(base))

    mat, cid = materialize_duplex_cluster(base, "oh_a")
    assert cid is not None
    cl = duplex_cluster_for(mat, "oh_a")
    assert cl is not None and cl.parent_cluster_id == "P" and cl.domain_ids
    # Pose moved off the OverhangSpec.
    spec = next(o for o in mat.overhangs if o.id == "oh_a")
    assert spec.rotation == [0.0, 0.0, 0.0, 1.0] and spec.translation == [0.0, 0.0, 0.0]
    # Geometry unchanged.
    mat_beads = _ovhg_beads(_geometry_for_design(mat))
    for bp in base_beads:
        assert np.allclose(base_beads[bp], mat_beads[bp], atol=1e-6), bp
    # Idempotent.
    again, cid2 = materialize_duplex_cluster(mat, "oh_a")
    assert cid2 == cid and len(again.cluster_transforms) == len(mat.cluster_transforms)

    # Round-trip: dematerialize restores the OverhangSpec pose + geometry, drops the cluster.
    back = dematerialize_duplex_cluster(mat, "oh_a")
    assert duplex_cluster_for(back, "oh_a") is None
    bspec = next(o for o in back.overhangs if o.id == "oh_a")
    assert np.allclose(bspec.rotation, r_w, atol=1e-5) and np.allclose(
        bspec.translation, t_w, atol=1e-5
    )
    back_beads = _ovhg_beads(_geometry_for_design(back))
    for bp in base_beads:
        assert np.allclose(base_beads[bp], back_beads[bp], atol=1e-6), bp


def _xf(quat, pivot, trans):
    from backend.core.deformation import _rot_from_quaternion

    R = _rot_from_quaternion(*quat)
    piv = np.asarray(pivot, float)
    t = np.asarray(trans, float)
    return lambda p: R @ (np.asarray(p, float) - piv) + piv + t


def _oh_segment(axes):
    ax = next(a for a in axes if a["helix_id"] == "dc_h")
    seg = next(s for s in ax["segments"] if s.get("ovhg_id") == "oh_a")
    return np.asarray(seg["start"], float), np.asarray(seg["end"], float)


def test_duplex_cluster_segment_axis_follows_child_composition():
    """The per-domain axis SEGMENT for the duplex follows T_parent(T_child(rest)) — the
    child-first ordering in deformed_helix_axes composes the child inside the parent, and
    duplex children are excluded from the whole-helix centre-line."""
    from backend.core.deformation import deformed_helix_axes
    from backend.core.duplex_cluster import (
        materialize_duplex_cluster,
        duplex_cluster_for,
    )

    ident = ClusterRigidTransform(
        id="P",
        name="p",
        helix_ids=["dc_h"],
        rotation=[0, 0, 0, 1],
        translation=[0, 0, 0],
        pivot=[0, 0, 0],
    )
    rest = _seed(ovhg_rotation=[0, 0, 0, 1], ovhg_translation=[0, 0, 0], parent=ident)
    rs, re = _oh_segment(deformed_helix_axes(rest))

    parent = ClusterRigidTransform(
        id="P",
        name="p",
        helix_ids=["dc_h"],
        rotation=_quat([0.2, 1.0, 0.3], 34.0),
        translation=[3.0, -1.0, 2.0],
        pivot=[0.5, 0.0, 1.0],
    )
    d = _seed(
        ovhg_rotation=_quat([0, 1, 0], 25.0),
        ovhg_translation=[0.0, 1.3, 0.4],
        parent=parent,
    )
    mat, _cid = materialize_duplex_cluster(d, "oh_a")
    child = duplex_cluster_for(mat, "oh_a")
    ms, me = _oh_segment(deformed_helix_axes(mat))

    Tp = _xf(parent.rotation, parent.pivot, parent.translation)
    Tc = _xf(child.rotation, child.pivot, child.translation)
    assert np.allclose(ms, Tp(Tc(rs)), atol=1e-6), (ms, Tp(Tc(rs)))
    assert np.allclose(me, Tp(Tc(re)), atol=1e-6), (me, Tp(Tc(re)))
    # And it actually moved relative to a parent-only pose (the child pose is real).
    assert not np.allclose(ms, Tp(rs), atol=1e-3)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    from backend.api import state as design_state

    design_state.set_design(_demo_design())


def test_headless_materialize_duplex_cluster_and_oracle():
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_duplex_cluster_materialized

    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["dc_h"],
        rotation=_quat([0.1, 1.0, 0.3], 28.0),
        translation=[2.0, -1.0, 4.0],
        pivot=[0.0, 1.0, 0.5],
    )
    d = _seed(
        ovhg_rotation=_quat([0, 1, 0], 30.0),
        ovhg_translation=[0.0, 1.4, 0.2],
        parent=parent,
    )
    design_state.set_design(d)
    before = design_state.get_or_404().model_copy(deep=True)
    after = hb.materialize_duplex_cluster("oh_a").model_copy(deep=True)

    assert_duplex_cluster_materialized(before, after, "oh_a")
    # Red: the oracle fires on a no-op (no cluster was created).
    with pytest.raises(AssertionError, match="no duplex cluster"):
        assert_duplex_cluster_materialized(before, before, "oh_a")


def test_validator_flags_uncleared_duplex_pose_and_bad_parent():
    from backend.core.validator import validate_design
    from backend.core.duplex_cluster import materialize_duplex_cluster

    parent = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["dc_h"],
        rotation=[0, 0, 0, 1],
        translation=[0, 0, 0],
        pivot=[0, 0, 0],
    )
    d = _seed(
        ovhg_rotation=_quat([0, 1, 0], 20.0),
        ovhg_translation=[0.0, 1.0, 0.0],
        parent=parent,
    )
    mat, _cid = materialize_duplex_cluster(d, "oh_a")
    # Clean materialization validates.
    assert not [
        r
        for r in validate_design(mat).results
        if not r.ok and "Cluster hierarchy" in r.message
    ]
    # Re-introduce a stale OverhangSpec pose on the cluster's driver → flagged.
    bad = mat.model_copy(
        update={
            "overhangs": [
                o.model_copy(update={"rotation": _quat([1, 0, 0], 10.0)})
                if o.id == "oh_a"
                else o
                for o in mat.overhangs
            ]
        }
    )
    msgs = [
        r.message
        for r in validate_design(bad).results
        if not r.ok and "Cluster hierarchy" in r.message
    ]
    assert msgs and "double-transform" in msgs[0]


@pytest.mark.skipif(
    not _REAL_FIXTURE.exists(),
    reason="relax_2x2_binding.nadoc missing (untracked; regen via AF-FIXTURES builder)",
)
def test_real_fixture_materialize_beads_neutral_and_no_stray_axis():
    """On the FROZEN 2x2 binding fixture (a real applied+relaxed direct connection):

      * backbone BEADS are bit-exact vs the OverhangSpec overlay (geometry-neutral), AND
      * NO stray axis: in the cluster design every overhang axis representation — the
        per-overhang shaft (`ovhg_axes`) AND the dedicated overhang-helix centre-line —
        runs THROUGH the duplex (near its beads), instead of the stick-at-lattice the
        overlay left behind (only the OverhangSpec-rotated DRIVER shaft followed; the
        driven shaft + the whole-helix centre-line stayed at the lattice = the reported
        stray line). Every NON-overhang helix centre-line is byte-neutral.

    Verified live against the running app's `workspace/2x2_OH_test.nadoc` (2026-07-01)."""
    import json
    from pathlib import Path

    from backend.core.models import Design
    from backend.core.deformation import (
        deformed_helix_axes,
        _apply_ovhg_rotations_to_axes,
    )
    from backend.core.duplex_cluster import materialize_duplex_cluster

    fx = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
    d = Design.model_validate(json.loads(fx.read_text()))
    drv = d.overhang_bindings[0].driver_oh_id
    dvn = d.overhang_bindings[0].driven_oh_id
    oh_helices = {
        dm.helix_id
        for s in d.strands
        for dm in s.domains
        if dm.overhang_id in (drv, dvn)
    }

    def _snapshot(des):
        nucs = _geometry_for_design(des)
        ax = deformed_helix_axes(des)
        _apply_ovhg_rotations_to_axes(des, ax, nucs)
        beads = {
            (n.get("overhang_id"), n["bp_index"], n["direction"]): np.asarray(
                n.get("backbone_position") or n.get("base_position"), float
            )
            for n in nucs
            if n.get("overhang_id") in (drv, dvn)
        }
        shafts, centreline = {}, {}
        for a in ax:
            centreline[a["helix_id"]] = (
                np.asarray(a["start"], float),
                np.asarray(a["end"], float),
            )
            for oid, seg in (a.get("ovhg_axes") or {}).items():
                if oid in (drv, dvn):
                    shafts[oid] = (
                        np.asarray(seg["start"], float),
                        np.asarray(seg["end"], float),
                    )
        return beads, shafts, centreline

    b0, _s0, c0 = _snapshot(d)
    mat, cid = materialize_duplex_cluster(d, drv)
    assert cid is not None
    b1, s1, c1 = _snapshot(mat)

    # 1) Beads bit-exact.
    assert set(b0) == set(b1) and b0
    assert max(float(np.linalg.norm(b0[k] - b1[k])) for k in b0) < 1e-6

    # 2) Every overhang SHAFT midpoint runs through that overhang's beads (no stray).
    for oid, (ss, ee) in s1.items():
        obeads = [b1[k] for k in b1 if k[0] == oid]
        assert (
            obeads
            and min(float(np.linalg.norm((ss + ee) / 2.0 - b)) for b in obeads) < 2.0
        ), oid

    # 3) The dedicated overhang-helix CENTRE-LINE runs through the duplex beads.
    dup_beads = list(b1.values())
    for hid in oh_helices:
        mid = (c1[hid][0] + c1[hid][1]) / 2.0
        assert min(float(np.linalg.norm(mid - b)) for b in dup_beads) < 2.0, hid

    # 4) Non-overhang helix centre-lines are byte-neutral.
    for hid in c0:
        if hid in oh_helices:
            continue
        assert np.allclose(c0[hid][0], c1[hid][0], atol=1e-6), hid
        assert np.allclose(c0[hid][1], c1[hid][1], atol=1e-6), hid


def test_conjugation_is_identity_when_parent_is_identity():
    """Sanity floor: with an identity parent the child transform == the world overlay."""
    ident = ClusterRigidTransform(
        id="P",
        name="part",
        helix_ids=["dc_h"],
        rotation=[0, 0, 0, 1],
        translation=[0, 0, 0],
        pivot=[0, 0, 0],
    )
    r_w = _quat([1.0, 0.0, 0.0], 18.0)
    t_w = [0.5, 0.0, -0.4]
    d = _seed(ovhg_rotation=r_w, ovhg_translation=t_w, parent=ident)
    pivot_world = _overhang_root_pivot(d, _geometry_for_design(d), "oh_a")
    q_c, piv_c, t_c = conjugate_world_pose_into_parent_rest(
        r_w, pivot_world, t_w, ident
    )
    # R_child == R_world; and applying (q_c, piv_c, t_c) at pivot 0 == the world overlay.
    assert np.allclose(q_c, r_w, atol=1e-6) or np.allclose(
        q_c, -np.asarray(r_w), atol=1e-6
    )
