"""Diagnostic-only linker preservation; never promotes candidate geometry."""

from dataclasses import replace

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.binding_relax import apply_bind_topology, compute_bind_topology
from backend.core.models import OverhangBinding
from experiments.direct_linker_candidate import (
    candidate_model, fit_candidate, positions, residue, residue_motion, root_endpoints, root_residues,
    transport_linkers,
)
from tests.test_part_duplex_commands import source


def relocate(original):
    a, b = original.overhangs[:2]
    ad = next(d for s in original.strands for d in s.domains if d.overhang_id == a.id)
    bd = next(d for s in original.strands for d in s.domains if d.overhang_id == b.id)
    length = abs(bd.end_bp - bd.start_bp) + 1
    step = 1 if ad.end_bp > ad.start_bp else -1
    binding = OverhangBinding(id="diagnostic-binding", name="Diagnostic", created_at=0.,
        sub_domain_a_id=a.sub_domains[0].id, sub_domain_b_id=b.sub_domains[0].id,
        overhang_a_id=a.id, overhang_b_id=b.id, driver_oh_id=a.id,
        driven_oh_id=b.id, bound=True)
    topology = compute_bind_topology(original, binding, driver_side="a",
        target_start_override=ad.end_bp, target_end_override=ad.end_bp - step * (length - 1))
    binding = binding.model_copy(update={"prior_driven_topology": topology.snapshot})
    return apply_bind_topology(original.copy_with(overhang_bindings=[binding]), topology)


def reachable_crossover_source(phase_deg=0.):
    """Pose parent B from independently matched sugar frames, without fitting.

    This is an explicit imported geometric fixture, not a native Extrude recipe.
    Both halves of B move together before binding, preserving its original root.
    """
    from backend.core.models import ClusterRigidTransform
    from scipy.spatial.transform import Rotation

    original = source(rooted=True)
    original = original.copy_with(helices=[h.model_copy(update={"phase_offset": np.deg2rad(phase_deg)})
                                          for h in original.helices])
    raw = relocate(original)
    before = build_atomistic_model(original, fast_bridges=True, apply_design_geometry=False)
    after = build_atomistic_model(raw, fast_bridges=True, apply_design_geometry=False)
    a = residue(before.atoms, root_residues(original, "oh-b")[1])
    b = residue(after.atoms, root_residues(raw, "oh-b")[1])
    rotation, origin, target = residue_motion(a, b, phosphate=True)
    cluster = ClusterRigidTransform(id="parent-b", name="Parent B", helix_ids=["b", "root-b"],
        pivot=origin.tolist(), rotation=Rotation.from_matrix(rotation).as_quat().tolist(),
        translation=(target - origin).tolist())
    return original.copy_with(cluster_transforms=[cluster])


def assert_linker_internal_bonds(before, after, original, relocated, oid):
    old, new = root_residues(original, oid), root_residues(relocated, oid)
    assert old[2] == new[2]
    for side, pairs in enumerate(((("C3'", "O3'"),),
                                 (("C5'", "O5'"), ("O5'", "P"), ("P", "OP1"), ("P", "OP2")))):
        a, b = residue(before.atoms, old[side]), residue(after.atoms, new[side])
        for names in pairs:
            p, q = positions([a[n] for n in names]), positions([b[n] for n in names])
            assert np.linalg.norm(p[0] - p[1]) == pytest.approx(np.linalg.norm(q[0] - q[1]), abs=1e-10)


@pytest.mark.parametrize("fast", [True, False], ids=["viewer", "export"])
@pytest.mark.parametrize("equal", [False, True], ids=["unequal", "equal"])
def test_transport_preserves_all_adjacent_bonds_and_unaffected_atoms(fast, equal):
    original = source(rooted=True, equal=equal)
    relocated = relocate(original)
    snapshots = (original.model_dump_json(), relocated.model_dump_json())
    before = build_atomistic_model(original, fast_bridges=fast)
    current = build_atomistic_model(relocated, fast_bridges=fast)
    candidate = candidate_model(relocated, original, ["oh-b"], fast_bridges=fast)
    assert current.bonds == candidate.bonds
    assert [replace(a, x=0., y=0., z=0.) for a in current.atoms] == [
        replace(a, x=0., y=0., z=0.) for a in candidate.atoms]
    affected = set(np.flatnonzero(np.linalg.norm(positions(current.atoms) - positions(candidate.atoms), axis=1) > 1e-10))
    assert {candidate.atoms[i].name for i in affected} <= {"O3'", "P", "OP1", "OP2", "O5'"}
    assert len(affected) == 5
    assert_linker_internal_bonds(before, candidate, original, relocated, "oh-b")
    assert snapshots == (original.model_dump_json(), relocated.model_dump_json())
    assert build_atomistic_model(relocated, fast_bridges=fast) == current


@pytest.mark.parametrize("fast", [True, False], ids=["viewer", "export"])
def test_candidate_keeps_distinct_native_viewer_export_endpoints(fast):
    original = source(rooted=True)
    relocated = relocate(original)
    viewer = root_endpoints(relocated, build_atomistic_model(relocated, fast_bridges=True), "oh-b")
    exporter = root_endpoints(relocated, build_atomistic_model(relocated, fast_bridges=False), "oh-b")
    np.testing.assert_array_equal(viewer["moving"], exporter["moving"])
    other = candidate_model(relocated, original, ["oh-b"], fast_bridges=not fast)
    candidate = candidate_model(relocated, original, ["oh-b"], fast_bridges=fast)
    ca, cb = (root_endpoints(relocated, m, "oh-b") for m in (candidate, other))
    assert sum(np.linalg.norm(ca[side] - cb[side]) for side in ("fixed", "moving")) > .008


def test_candidate_restores_native_hook_after_unsupported_geometry():
    from backend.core import deformation

    original = source(rooted=True)
    native = deformation.apply_deformations_to_atoms
    with pytest.raises(ValueError, match="unambiguous overhang"):
        candidate_model(relocate(original), original, ["missing"], fast_bridges=True)
    assert deformation.apply_deformations_to_atoms is native


def test_candidate_refuses_a_degenerate_sugar_frame():
    original = source(rooted=True)
    relocated = relocate(original)
    before = build_atomistic_model(original, fast_bridges=True, apply_design_geometry=False)
    after = build_atomistic_model(relocated, fast_bridges=True, apply_design_geometry=False)
    root = root_residues(relocated, "oh-b")
    sugar = residue(after.atoms, root[1])
    sugar["C4'"].x, sugar["C4'"].y, sugar["C4'"].z = positions([sugar["C5'"]])[0]
    with np.errstate(invalid="ignore"):
        with pytest.raises(ValueError, match="degenerate residue frame"):
            transport_linkers(after.atoms, relocated, before.atoms, original, ["oh-b"])


@pytest.mark.parametrize("phase", range(0, 360, 10))
def test_candidate_closes_both_builders_over_a_full_phase_sweep(phase):
    original = reachable_crossover_source(phase)
    raw = relocate(original)
    placed = fit_candidate(raw, original, "oh-a", ["oh-b"], ["oh-a", "oh-b"])
    assert placed == raw  # Independently constructed feasible pose needs no motion.
    for fast in (True, False):
        before = build_atomistic_model(original, fast_bridges=fast)
        after = candidate_model(placed, original, ["oh-b"], fast_bridges=fast)
        for oid in ("oh-a", "oh-b"):
            assert root_endpoints(placed, after, oid)["length_nm"] == pytest.approx(
                root_endpoints(original, before, oid)["length_nm"], abs=1e-8)
        assert_linker_internal_bonds(before, after, original, placed, "oh-b")


def test_preserved_linker_does_not_make_unreachable_parent_parts_reachable():
    from fastapi import HTTPException

    original = source(rooted=True)
    raw = relocate(original)
    before = raw.model_dump_json()
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        fit_candidate(raw, original, "oh-a", ["oh-b"], ["oh-a", "oh-b"])
    assert raw.model_dump_json() == before


@pytest.mark.parametrize("fast", [True, False], ids=["viewer", "export"])
def test_native_extrusions_preserve_adjacent_bonds_with_shared_host_strand(fast):
    from tests.test_part_pending_connection_versions import native_prefix

    original = native_prefix.__wrapped__()
    raw = relocate(original)
    a, b = original.overhangs
    assert a.strand_id == b.strand_id
    before = build_atomistic_model(original, fast_bridges=fast)
    after = candidate_model(raw, original, [b.id], fast_bridges=fast)
    assert_linker_internal_bonds(before, after, original, raw, b.id)
    # The untouched other root is resolved by direction, even at a shared bp.
    current = build_atomistic_model(raw, fast_bridges=fast)
    for side in ("fixed", "moving"):
        np.testing.assert_array_equal(root_endpoints(raw, current, a.id)[side],
                                      root_endpoints(raw, after, a.id)[side])


@pytest.mark.parametrize("angle", [-25., 35.])
def test_candidate_fitter_recovers_roots_after_manual_duplex_motion(angle):
    from backend.core.overhang_root_constraints import rotate_overhang_about
    from scipy.spatial.transform import Rotation

    original = reachable_crossover_source()
    raw = relocate(original)
    moved = rotate_overhang_about(raw, "oh-a", Rotation.from_euler("y", angle, degrees=True).as_matrix(),
                                 np.zeros(3), translation=np.array([.1, -.2, .05]), materialize=False)
    # Building the candidate does not undo a deliberate manual stretch.
    before = build_atomistic_model(original, fast_bridges=True)
    manual = candidate_model(moved, original, ["oh-b"], fast_bridges=True)
    assert abs(root_endpoints(moved, manual, "oh-b")["length_nm"]
               - root_endpoints(original, before, "oh-b")["length_nm"]) > .01
    placed = fit_candidate(moved, original, "oh-a", ["oh-b"], ["oh-a", "oh-b"])
    assert placed.cluster_transforms == moved.cluster_transforms
    for fast in (True, False):
        before = build_atomistic_model(original, fast_bridges=fast)
        after = candidate_model(placed, original, ["oh-b"], fast_bridges=fast)
        assert_linker_internal_bonds(before, after, original, placed, "oh-b")


def test_existing_snapshot_reconstructs_same_candidate_as_explicit_original():
    from backend.core.binding_relax import revert_bind_topology

    original = reachable_crossover_source()
    raw = relocate(original)
    recovered = revert_bind_topology(raw, raw.overhang_bindings[0].prior_driven_topology)
    for fast in (True, False):
        assert candidate_model(raw, recovered, ["oh-b"], fast_bridges=fast) == candidate_model(
            raw, original, ["oh-b"], fast_bridges=fast)


def test_native_extrude_layout_still_refuses_with_preserved_linkers():
    from fastapi import HTTPException
    from tests.test_part_pending_connection_versions import native_prefix

    original = native_prefix.__wrapped__()
    raw = relocate(original)
    a, b = original.overhangs
    before = raw.model_dump_json()
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        fit_candidate(raw, original, a.id, [b.id], [a.id, b.id])
    assert raw.model_dump_json() == before
