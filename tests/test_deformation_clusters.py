"""
Tests for cluster-scoped bend/twist deformations.

The bend/twist API accepts a ``cluster_ids`` list. When non-empty, the
``affected_helix_ids`` of the resulting DeformationOp is filtered to the
union of those clusters' helix_ids, so two clusters with overlapping bp
ranges can be bent or twisted independently within the same NADOC design.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterRigidTransform

client = TestClient(app)


# ── Fixture: 6-helix bundle with two disjoint clusters ─────────────────────────


@pytest.fixture(autouse=True)
def reset_state(_design):
    yield


@pytest.fixture()
def _design():
    """6-helix HC bundle, 420 bp long. First 3 helices → cluster A, last 3 → cluster B."""
    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    design = make_bundle_design(cells, length_bp=420)
    h_ids = [h.id for h in design.helices]
    cluster_a = ClusterRigidTransform(name="ArmA", helix_ids=h_ids[:3])
    cluster_b = ClusterRigidTransform(name="ArmB", helix_ids=h_ids[3:])
    design = design.copy_with(cluster_transforms=[cluster_a, cluster_b])
    design_state.set_design(design)
    return design


def _post_bend(cluster_ids: list[str]) -> dict:
    """POST /design/deformation for a 30° bend across bp 100→200."""
    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 100,
            "plane_b_bp": 200,
            "params": {"angle_deg": 30.0, "direction_deg": 0.0},
            "cluster_ids": cluster_ids,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_cluster_ids_filters_affected_helices(_design):
    """Bend scoped to cluster A → affected_helix_ids ⊂ cluster A's helices."""
    cluster_a = _design.cluster_transforms[0]
    _post_bend(cluster_ids=[cluster_a.id])

    design = design_state.get_or_404()
    assert len(design.deformations) == 1
    op = design.deformations[0]
    assert op.cluster_ids == [cluster_a.id]
    assert set(op.affected_helix_ids).issubset(set(cluster_a.helix_ids))
    assert set(op.affected_helix_ids) & set(_design.cluster_transforms[1].helix_ids) == set()


def test_two_overlapping_bends_on_different_clusters_coexist(_design):
    """Two bends, same bp range, different cluster scopes → independent helix sets."""
    cluster_a, cluster_b = _design.cluster_transforms
    _post_bend(cluster_ids=[cluster_a.id])
    _post_bend(cluster_ids=[cluster_b.id])

    design = design_state.get_or_404()
    assert len(design.deformations) == 2
    op_a, op_b = design.deformations
    assert op_a.cluster_ids == [cluster_a.id]
    assert op_b.cluster_ids == [cluster_b.id]
    assert set(op_a.affected_helix_ids).isdisjoint(op_b.affected_helix_ids)


def test_multi_cluster_scope_unions_helices(_design):
    """cluster_ids = [A, B] → affected_helix_ids = union of both clusters' helices."""
    cluster_a, cluster_b = _design.cluster_transforms
    _post_bend(cluster_ids=[cluster_a.id, cluster_b.id])

    design = design_state.get_or_404()
    op = design.deformations[0]
    assert set(op.cluster_ids) == {cluster_a.id, cluster_b.id}
    expected = set(cluster_a.helix_ids) | set(cluster_b.helix_ids)
    assert set(op.affected_helix_ids) == expected


def test_empty_cluster_ids_is_unscoped(_design):
    """No cluster scope → affected_helix_ids comes from helices_crossing_planes."""
    _post_bend(cluster_ids=[])

    design = design_state.get_or_404()
    op = design.deformations[0]
    assert op.cluster_ids == []
    # All 6 helices span bp 100→200, so all should be affected.
    assert len(op.affected_helix_ids) == 6


def test_unknown_cluster_id_is_dropped(_design):
    """A non-existent cluster_id is silently dropped from the resolved scope."""
    cluster_a = _design.cluster_transforms[0]
    _post_bend(cluster_ids=[cluster_a.id, "does-not-exist"])

    design = design_state.get_or_404()
    op = design.deformations[0]
    assert op.cluster_ids == [cluster_a.id]
    assert set(op.affected_helix_ids).issubset(set(cluster_a.helix_ids))


def test_unaffected_cluster_does_not_translate_when_other_cluster_bent():
    """Regression: with a bend op present that does NOT cover this helix, the
    helix's geometry must be byte-identical to the un-deformed positions.

    Previously the frame-math path ran even for unaffected helices and could
    shift them by a small per-cluster amount because the cs_offset / centroid
    arithmetic doesn't perfectly preserve identity when the arm has mixed
    bp_starts or axis offsets. Now short-circuited via _ops_affecting_helix.
    """
    import numpy as np

    from backend.core.deformation import (
        deformed_nucleotide_positions, deformed_nucleotide_arrays,
        deformed_helix_axes,
    )

    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    design = make_bundle_design(cells, length_bp=420)
    h_ids = [h.id for h in design.helices]
    cluster_a = ClusterRigidTransform(name="ArmA", helix_ids=h_ids[:3])
    cluster_b = ClusterRigidTransform(name="ArmB", helix_ids=h_ids[3:])
    design = design.copy_with(cluster_transforms=[cluster_a, cluster_b])
    design_state.set_design(design)

    h_b = design.find_helix(h_ids[3])

    before = [n.position.copy() for n in deformed_nucleotide_positions(h_b, design)]
    before_arrs = deformed_nucleotide_arrays(h_b, design)['positions'].copy()
    before_axes = next(
        (a for a in deformed_helix_axes(design) if a['helix_id'] == h_b.id), None,
    )
    assert before_axes is not None

    # 30° bend scoped to cluster A only.
    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 100,
            "plane_b_bp": 200,
            "params": {"angle_deg": 30.0, "direction_deg": 0.0},
            "cluster_ids": [cluster_a.id],
        },
    )
    assert r.status_code == 200, r.text

    bent_design = design_state.get_or_404()
    after = [n.position.copy() for n in deformed_nucleotide_positions(h_b, bent_design)]
    after_arrs = deformed_nucleotide_arrays(h_b, bent_design)['positions']
    after_axes = next(
        (a for a in deformed_helix_axes(bent_design) if a['helix_id'] == h_b.id), None,
    )
    assert after_axes is not None

    for i, (p0, p1) in enumerate(zip(before, after)):
        assert np.allclose(p0, p1, atol=1e-9), (
            f"ArmB nucleotide #{i} moved: before={p0.tolist()} after={p1.tolist()}"
        )
    assert np.allclose(before_arrs, after_arrs, atol=1e-9)
    assert np.allclose(np.array(before_axes['start']), np.array(after_axes['start']), atol=1e-9)
    assert np.allclose(np.array(before_axes['end']),   np.array(after_axes['end']),   atol=1e-9)
    assert np.allclose(
        np.array(before_axes['samples']), np.array(after_axes['samples']), atol=1e-9,
    )


def test_helix_axis_samples_use_arm_local_bp_for_off_anchor_helices():
    """Regression: deformed_helix_axes was passing helix-local bp to
    _frame_at_bp (which expects arm-local). For a helix whose bp_start ≠
    arm_min_bp_start, the axis line was sampled at a wrong Z — it appeared
    "some distance away" from the nucleotides while the bond geometry was
    drawn correctly.

    Verified on a cluster with helices at bp_starts 114/123/129/135 (the
    Ultimate Polymer Hinge cluster 3 pattern) with a 0° bend op present,
    which forces the affected helices through the frame-math path.
    """
    import numpy as np

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.deformation import deformed_helix_axes
    from backend.core.models import Direction, Helix, Strand, StrandType, Domain, Vec3, Design

    def _z_helix(hid, x, bp_start, length):
        z0 = bp_start * BDNA_RISE_PER_BP
        return Helix(
            id=hid,
            axis_start=Vec3(x=x, y=0.0, z=z0),
            axis_end=Vec3(x=x, y=0.0, z=z0 + length * BDNA_RISE_PER_BP),
            phase_offset=0.0,
            length_bp=length,
            bp_start=bp_start,
        )

    helices = [
        _z_helix("h0", -4.5,  114, 30),
        _z_helix("h1", -2.25, 123, 21),
        _z_helix("h2",  0.0,  114, 30),
        _z_helix("h3",  2.25, 129, 15),
        _z_helix("h4",  4.5,  114, 30),
        _z_helix("h5",  6.75, 135,  9),
    ]
    scaf = Strand(
        id="s",
        domains=[Domain(helix_id="h0", start_bp=114, end_bp=143, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    cluster_ = ClusterRigidTransform(name="C", helix_ids=[h.id for h in helices])
    design = Design(helices=helices, strands=[scaf], cluster_transforms=[cluster_])
    design_state.set_design(design)

    # Add a 0° bend covering all helices so each helix is in op.affected_helix_ids
    # and goes through the frame-math axis path (not the short-circuit).
    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 114,
            "plane_b_bp": 143,
            "params": {"angle_deg": 0.0, "direction_deg": 0.0},
            "cluster_ids": [cluster_.id],
            "affected_helix_ids": [h.id for h in helices],
        },
    )
    assert r.status_code == 200, r.text

    bent_design = design_state.get_or_404()
    axes = deformed_helix_axes(bent_design)
    axes_by_id = {a["helix_id"]: a for a in axes}

    # Each helix's axis line should start at (x, 0, bp_start * RISE) — its
    # canonical straight position — because the bend is 0°.
    for h in helices:
        ax = axes_by_id[h.id]
        expected_start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        actual_start = np.array(ax["start"])
        assert np.allclose(expected_start, actual_start, atol=1e-6), (
            f"{h.id} (bp_start={h.bp_start}): axis start expected {expected_start.tolist()} "
            f"got {actual_start.tolist()} (delta z = {actual_start[2] - expected_start[2]:.4f})"
        )


def test_frame_at_bp_uses_min_bp_start_not_first_helix():
    """Regression: _frame_at_bp used ``helices[0].bp_start`` as the arm anchor
    for converting global op-plane bp to arm-local. When the first helix in
    the arm wasn't the one with the smallest bp_start, the op planes shifted
    by ``(helices[0].bp_start − arm_min_bp_start) × RISE`` from where the
    centroid math placed them — manifesting as helix-axis lines drifting from
    the (correctly-positioned) nucleotides, since the nucleotide path used
    arm_min_bp_start directly while _frame_at_bp internally used helices[0].
    Real-world trigger: a Scaffold Cluster spanning all 74 helices in
    Ultimate Polymer Hinge, where design.helices[0] starts mid-bundle.
    """
    import numpy as np

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.deformation import deformed_helix_axes
    from backend.core.models import Direction, Helix, Strand, StrandType, Domain, Vec3, Design

    def _z_helix(hid, x, bp_start, length):
        z0 = bp_start * BDNA_RISE_PER_BP
        return Helix(
            id=hid,
            axis_start=Vec3(x=x, y=0.0, z=z0),
            axis_end=Vec3(x=x, y=0.0, z=z0 + length * BDNA_RISE_PER_BP),
            phase_offset=0.0,
            length_bp=length,
            bp_start=bp_start,
        )

    # ORDER MATTERS: the helix with the LARGEST bp_start is listed first, so
    # design.helices[0].bp_start = 135 ≠ arm_min_bp_start = 114. This exposes
    # the helices[0]-vs-min anchor mismatch in _frame_at_bp.
    helices = [
        _z_helix("h5",  6.75, 135,  9),   # first, but largest bp_start
        _z_helix("h0", -4.5,  114, 30),
        _z_helix("h1", -2.25, 123, 21),
        _z_helix("h2",  0.0,  114, 30),
        _z_helix("h3",  2.25, 129, 15),
        _z_helix("h4",  4.5,  114, 30),
    ]
    scaf = Strand(
        id="s",
        domains=[Domain(helix_id="h0", start_bp=114, end_bp=143, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    cluster_ = ClusterRigidTransform(name="C", helix_ids=[h.id for h in helices])
    design = Design(helices=helices, strands=[scaf], cluster_transforms=[cluster_])
    design_state.set_design(design)

    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 114,
            "plane_b_bp": 143,
            "params": {"angle_deg": 0.0, "direction_deg": 0.0},
            "cluster_ids": [cluster_.id],
            "affected_helix_ids": [h.id for h in helices],
        },
    )
    assert r.status_code == 200, r.text

    bent = design_state.get_or_404()
    axes_by_id = {a["helix_id"]: a for a in deformed_helix_axes(bent)}

    for h in helices:
        ax = axes_by_id[h.id]
        expected = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        actual   = np.array(ax["start"])
        assert np.allclose(expected, actual, atol=1e-6), (
            f"{h.id} (bp_start={h.bp_start}): axis start expected {expected.tolist()} "
            f"got {actual.tolist()}"
        )


def test_mixed_bp_start_cluster_zero_angle_bend_does_not_translate():
    """Regression: a cluster whose helices have mixed bp_starts (typical for
    routing-adjusted sub-clusters) was uniformly translated forward along the
    tangent by (avg(bp_start) − arm_min_bp_start) × BDNA_RISE_PER_BP every time
    a deformation op covered the cluster, even at angle=0.

    Triggered by clicking plane A on a cluster like Ultimate Polymer Hinge's
    Geometry Cluster 3 (bp_starts 114/123/129/135). Fixed by projecting each
    helix's axis_start back to arm_min_bp before averaging in
    _bundle_centroid_and_tangent.
    """
    import numpy as np

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.deformation import deformed_nucleotide_positions
    from backend.core.models import Direction, Helix, Strand, StrandType, Domain, Vec3, Design

    def _z_helix(hid, x, bp_start, length):
        z0 = bp_start * BDNA_RISE_PER_BP
        return Helix(
            id=hid,
            axis_start=Vec3(x=x, y=0.0, z=z0),
            axis_end=Vec3(x=x, y=0.0, z=z0 + length * BDNA_RISE_PER_BP),
            phase_offset=0.0,
            length_bp=length,
            bp_start=bp_start,
        )

    helices = [
        _z_helix("h0", -4.5,  114, 30),
        _z_helix("h1", -2.25, 123, 21),
        _z_helix("h2",  0.0,  114, 30),
        _z_helix("h3",  2.25, 129, 15),
        _z_helix("h4",  4.5,  114, 30),
        _z_helix("h5",  6.75, 135,  9),
    ]
    # A no-op-ish scaffold to make the design valid (covers h0 forward).
    scaf = Strand(
        id="s",
        domains=[Domain(helix_id="h0", start_bp=114, end_bp=143, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    cluster_ = ClusterRigidTransform(name="C", helix_ids=[h.id for h in helices])
    design = Design(helices=helices, strands=[scaf], cluster_transforms=[cluster_])
    design_state.set_design(design)

    before = {
        (n.helix_id, n.bp_index, n.direction): np.array(n.position)
        for h in helices
        for n in deformed_nucleotide_positions(h, design)
    }

    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 120,
            "plane_b_bp": 140,
            "params": {"angle_deg": 0.0, "direction_deg": 0.0},
            "cluster_ids": [cluster_.id],
        },
    )
    assert r.status_code == 200, r.text

    bent_design = design_state.get_or_404()
    after = {
        (n.helix_id, n.bp_index, n.direction): np.array(n.position)
        for h in helices
        for n in deformed_nucleotide_positions(h, bent_design)
    }

    for key, p0 in before.items():
        p1 = after[key]
        assert np.allclose(p0, p1, atol=1e-9), (
            f"{key} shifted by zero-angle bend: before={p0.tolist()} after={p1.tolist()}"
        )


def test_default_cluster_does_not_leak_bend_to_other_clusters():
    """Regression: when an umbrella default cluster contains all helices and the
    user bends a specific non-default cluster, the bend must not leak through
    the default cluster onto helices in the OTHER non-default cluster.

    Before the fix, the physics-layer arm filter picked clusters[0] which could
    be the default cluster — making the filter a no-op and letting the bend
    bleed across cluster boundaries.
    """
    import numpy as np

    from backend.core.deformation import deformed_nucleotide_positions

    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    design = make_bundle_design(cells, length_bp=420)
    h_ids = [h.id for h in design.helices]
    default = ClusterRigidTransform(name="All", helix_ids=h_ids, is_default=True)
    cluster_a = ClusterRigidTransform(name="ArmA", helix_ids=h_ids[:3])
    cluster_b = ClusterRigidTransform(name="ArmB", helix_ids=h_ids[3:])
    design = design.copy_with(cluster_transforms=[default, cluster_a, cluster_b])
    design_state.set_design(design)

    # Snapshot the un-bent positions of an ArmB helix.
    h_b = design.find_helix(h_ids[3])
    before = {
        (n.bp_index, n.direction): np.array(n.position)
        for n in deformed_nucleotide_positions(h_b, design)
    }

    # Bend scoped to ArmA only.
    r = client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": 100,
            "plane_b_bp": 200,
            "params": {"angle_deg": 45.0, "direction_deg": 0.0},
            "cluster_ids": [cluster_a.id],
        },
    )
    assert r.status_code == 200, r.text

    bent_design = design_state.get_or_404()
    after = {
        (n.bp_index, n.direction): np.array(n.position)
        for n in deformed_nucleotide_positions(h_b, bent_design)
    }

    # Every ArmB nucleotide should be at its un-bent position.
    for key, p0 in before.items():
        p1 = after[key]
        assert np.allclose(p0, p1, atol=1e-6), (
            f"ArmB helix {h_b.id} bp {key} moved by bend scoped to ArmA: "
            f"before={p0.tolist()} after={p1.tolist()}"
        )
