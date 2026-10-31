"""Both covalent roots, native pairing and manual movement remain distinct contracts."""

import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.core.binding_relax import apply_bind_topology, compute_bind_topology
from backend.core.direct_root_placement import capture_root_lengths, place_direct_roots
from backend.core.models import OverhangBinding
from backend.core.overhang_root_constraints import overhang_root_bond
from tests.test_direct_connection_unified import _seed


def unplaced(source):
    binding = OverhangBinding(
        name="B1", sub_domain_a_id=source.overhangs[0].sub_domains[0].id,
        sub_domain_b_id=source.overhangs[1].sub_domains[0].id,
        overhang_a_id="oh_a", overhang_b_id="oh_b", driver_oh_id="oh_a",
        driven_oh_id="oh_b", connection_type="end-to-root", bound=True,
    )
    topology = compute_bind_topology(source, binding, driver_side="a")
    binding = binding.model_copy(update={"prior_driven_topology": topology.snapshot})
    return apply_bind_topology(source.copy_with(overhang_bindings=[binding]), topology)


def reachable_source(angle=45.):
    """Place B's parent at a known reachable root without using the fitter."""
    source = _seed(cluster_b_translation=(6., 3., 2.))
    raw = unplaced(source)
    a = overhang_root_bond(raw, "oh_a")
    b = overhang_root_bond(raw, "oh_b")
    original_b = overhang_root_bond(source, "oh_b")
    rotation = Rotation.from_euler("y", angle, degrees=True).as_matrix()
    moving = rotation @ (b.moving - a.fixed) + a.fixed
    desired_fixed = moving + rotation @ (original_b.fixed - original_b.moving)
    delta = desired_fixed - b.fixed
    return source.copy_with(cluster_transforms=[
        c.model_copy(update={"translation": (np.asarray(c.translation) + delta).tolist()})
        if c.id == "cB" else c for c in source.cluster_transforms
    ])


@pytest.mark.parametrize("angle", [0., 45., -75.])
def test_rigid_placement_preserves_both_native_root_lengths(angle):
    source = reachable_source(angle)
    targets = capture_root_lengths(source, ["oh_a", "oh_b"])
    raw = unplaced(source)
    before = raw.model_dump_json()
    placed = place_direct_roots(raw, "oh_a", targets)
    assert raw.model_dump_json() == before
    assert placed.strands == raw.strands
    assert placed.cluster_transforms == raw.cluster_transforms
    assert placed.helices == raw.helices
    for oid, expected in targets.items():
        for builder, value in expected.items():
            bond = overhang_root_bond(placed, oid, fast_bridges=builder == "viewer")
            assert bond.length_nm == pytest.approx(value, abs=1e-8)
            np.testing.assert_allclose(bond.fixed, overhang_root_bond(raw, oid, fast_bridges=builder == "viewer").fixed, atol=1e-10)
    again = place_direct_roots(placed, "oh_a", targets)
    for oid, expected in capture_root_lengths(placed, targets).items():
        assert capture_root_lengths(again, targets)[oid] == pytest.approx(expected, abs=1e-10)


def test_unreachable_pair_refuses_without_mutating_topology_or_pose():
    source = _seed(cluster_b_translation=(6., 3., 2.))
    raw = unplaced(source)
    before = raw.model_dump_json()
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        place_direct_roots(raw, "oh_a", capture_root_lengths(source, ["oh_a", "oh_b"]))
    assert raw.model_dump_json() == before


def test_root_lookup_distinguishes_two_paired_domains_on_one_strand():
    from backend.core.atomistic import build_atomistic_model
    from tests.test_part_pending_connection_versions import native_prefix
    from tests.test_part_connection_application_commands import application_prefix

    source = application_prefix.__wrapped__(native_prefix.__wrapped__())
    a, b = source.overhangs
    binding = OverhangBinding(name="probe", sub_domain_a_id=a.sub_domains[0].id,
        sub_domain_b_id=b.sub_domains[0].id, overhang_a_id=a.id,
        overhang_b_id=b.id, driver_oh_id=a.id, driven_oh_id=b.id, bound=True)
    raw = apply_bind_topology(source.copy_with(overhang_bindings=[binding]),
                              compute_bind_topology(source, binding, driver_side="a"))
    strand = next(s for s in raw.strands if s.id == a.strand_id)
    assert a.strand_id == b.strand_id
    for fast in (True, False):
        model = build_atomistic_model(raw, fast_bridges=fast)
        for oid in (a.id, b.id):
            index, domain = next((i, d) for i, d in enumerate(strand.domains) if d.overhang_id == oid)
            bp, name = (domain.end_bp, "O3'") if index == 0 else (domain.start_bp, "P")
            # Same strand, helix and bp has one atom of each duplex direction.
            candidates = [atom for atom in model.atoms if atom.strand_id == strand.id
                and atom.helix_id == domain.helix_id and atom.bp_index == bp and atom.name == name]
            assert len(candidates) == 2
            expected = next(atom for atom in candidates if atom.direction == domain.direction.value)
            np.testing.assert_allclose(overhang_root_bond(raw, oid, fast_bridges=fast).moving,
                                       [expected.x, expected.y, expected.z], atol=1e-12)


def test_changed_linker_convention_refuses_without_publishing():
    from tests.test_part_duplex_commands import source, build, connect_params

    original = source(rooted=True)
    before = original.model_dump_json()
    with pytest.raises(HTTPException, match="native viewer and export root linkers"):
        build("duplex-connect", original, connect_params())
    assert original.model_dump_json() == before


def test_direct_connect_preserves_roots_and_persists_constraints():
    from backend.api.connection_version_direct import materialize_direct
    from backend.core.duplex_cluster import duplex_cluster_for

    source = reachable_source()
    before = source.model_dump_json()
    expected = capture_root_lengths(source, ["oh_a", "oh_b"])
    placed = materialize_direct(source, "oh_a", "oh_b", "free_end", "root", "end-to-root")
    assert source.model_dump_json() == before
    assert placed.overhang_bindings[0].prior_driven_topology["root_bond_lengths_nm"] == expected
    restored = type(placed).model_validate_json(placed.model_dump_json())
    for oid, values in expected.items():
        assert capture_root_lengths(restored, expected)[oid] == pytest.approx(values, abs=1e-8)
    assert len(placed.duplexes) == 1
    assert duplex_cluster_for(placed, "oh_a") is not None
    for original in source.cluster_transforms:
        assert next(c for c in placed.cluster_transforms if c.id == original.id) == original


def test_direct_connect_refuses_unreachable_input_atomically():
    from backend.api.connection_version_direct import materialize_direct

    source = _seed(cluster_b_translation=(6., 3., 2.))
    before = source.model_dump_json()
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        materialize_direct(source, "oh_a", "oh_b", "free_end", "root", "end-to-root")
    assert source.model_dump_json() == before


def test_manual_duplex_move_still_allows_stretching():
    from backend.api.connection_version_direct import materialize_direct
    from backend.core.duplex_cluster import duplex_cluster_for

    placed = materialize_direct(reachable_source(), "oh_a", "oh_b", "free_end", "root", "end-to-root")
    child = duplex_cluster_for(placed, "oh_a")
    moved = placed.copy_with(cluster_transforms=[c.model_copy(update={
        "translation": (np.asarray(c.translation) + [10., 0., 0.]).tolist()})
        if c.id == child.id else c for c in placed.cluster_transforms])
    assert overhang_root_bond(moved, "oh_a").length_nm > 5
    assert overhang_root_bond(moved, "oh_b").length_nm > 5


@pytest.mark.parametrize("moved_id", ["duplex", "cB"])
def test_relax_restores_root_lengths_after_manual_move(moved_id):
    from backend.api.connection_version_direct import materialize_direct
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.duplex_cluster import duplex_cluster_for

    placed = materialize_direct(reachable_source(), "oh_a", "oh_b", "free_end", "root", "end-to-root")
    targets = capture_root_lengths(placed, ["oh_a", "oh_b"])
    child = duplex_cluster_for(placed, "oh_a")
    identity = child.id if moved_id == "duplex" else moved_id
    moved = placed.copy_with(cluster_transforms=[c.model_copy(update={
        "translation": (np.asarray(c.translation) + [10., 0., 0.]).tolist()})
        if c.id == identity else c for c in placed.cluster_transforms])
    before = moved.model_dump_json()
    settled, info = relax_direct_binding(moved, "oh_a", "oh_b")
    assert moved.model_dump_json() == before
    assert settled.strands == moved.strands
    for oid, expected in targets.items():
        assert capture_root_lengths(settled, targets)[oid] == pytest.approx(expected, abs=1e-8)
    if moved_id == "duplex":
        assert info["moved_cluster_ids"] == []
    again, second = relax_direct_binding(settled, "oh_a", "oh_b")
    assert second["moved_cluster_ids"] == []
    for oid in targets:
        np.testing.assert_allclose(overhang_root_bond(again, oid).moving,
                                   overhang_root_bond(settled, oid).moving, atol=1e-8)


def test_relax_refuses_when_parent_joint_cannot_reach():
    from backend.api.connection_version_direct import materialize_direct
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.models import ClusterJoint

    placed = materialize_direct(reachable_source(), "oh_a", "oh_b", "free_end", "root", "end-to-root")
    moved = placed.copy_with(cluster_transforms=[c.model_copy(update={
        "translation": (np.asarray(c.translation) + [10., 0., 0.]).tolist()})
        if c.id == "cB" else c for c in placed.cluster_transforms], cluster_joints=[ClusterJoint(
            id="locked", cluster_id="cB", local_axis_origin=[0., 0., 0.],
            local_axis_direction=[0., 1., 0.], min_angle_deg=0., max_angle_deg=0.)])
    before = moved.model_dump_json()
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        relax_direct_binding(moved, "oh_a", "oh_b")
    assert moved.model_dump_json() == before
