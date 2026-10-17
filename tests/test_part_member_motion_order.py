"""Native counterexamples for the proposed selected-material motion contract.

These characterize current native behavior, not approved molecular placements. The
candidate is only rigid arithmetic on detached native output in this test: no
schema, renderer, export, saved model, or production evaluator consumes it.
The contract is chronological world-space motion of material selected at a
feature prefix. Existing placement owners and a new final pass are insufficient.
"""

from uuid import UUID

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import crud, part_proof_commands as commands
from backend.core import models as m
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_extension_placement_preservation import _append_extension, _inputs
from tests.test_part_transform_preview import snapshot


def _source():
    return snapshot(
        create_empty_part("Isolated motion ordering probe", "HONEYCOMB"),
        "bundle-create",
        crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=8,
                           ligate_adjacent=False, history_seed=UUID(int=26001)
                           ).model_dump(mode="json"), "bundle",
    )


def _pose(axis, angle, pivot, translation):
    return {"rotation": Rotation.from_euler(axis, angle, degrees=True).as_quat().tolist(),
            "pivot": pivot, "translation": translation}


N = _pose("x", 90, [1, 2, 3], [.25, -.5, .75])
M = _pose("z", 90, [2, -1, .5], [-.5, 1, 2])
D = _pose("y", 0, [0, 0, 0], [3, -2, 1])


def _rigid(points, pose):
    """Independent affine oracle; no native pose/composition helper reused."""
    pivot = np.asarray(pose["pivot"])
    return (Rotation.from_quat(pose["rotation"]).apply(np.asarray(points) - pivot)
            + pivot + pose["translation"])


def _target(source, direction):
    strand = next(s for s in source.strands
                  if s.domains[0].helix_id == source.helices[0].id
                  and s.domains[0].direction == direction)
    return strand, {"kind": "base", "helix_id": source.helices[0].id,
                    "bp_index": 3, "direction": direction.value, "copy_k": 0}


def _nucleotide(source, target, pose, identity, *, compose=False):
    return snapshot(source, "nucleotide-transform", {
        **target, **pose, "compose": compose, "history_seed": str(UUID(int=26002)),
    }, identity)


def _owner(source, strand=None):
    refs = [m.DomainRef(strand_id=strand.id, domain_index=0)] if strand else []
    owner = m.ClusterRigidTransform(id="probe-owner", name="Existing placement",
        helix_ids=[source.helices[0].id], domain_ids=refs, **M)
    return _append(source, m.ClusterCreateLogEntry(id="placement", proof_version=2,
        cluster_id=owner.id, name=owner.name, helix_ids=owner.helix_ids,
        domain_ids=owner.domain_ids, cluster_snapshot=owner))


def _full(source):
    return {(n["helix_id"], n["bp_index"], n["direction"], n.get("copy_k", 0)): n
            for n in _geometry_for_design(source)}


def _key(target):
    return target["helix_id"], target["bp_index"], target["direction"], target["copy_k"]


def _verify(source):
    report = assess_part_history(source, execute=commands.execute,
                                 dependencies=commands.dependencies)
    assert report["status"] == "verified" and report["native_editable"], report


@pytest.mark.parametrize("direction", list(m.Direction))
def test_appended_placement_owner_is_not_a_world_motion_of_displayed_material(direction):
    base = _source()
    strand, target = _target(base, direction)
    posed = _nucleotide(base, target, N, "prior-residue")
    locked = posed.model_dump_json()
    candidate_owner = _owner(posed, strand)
    owner_only = _owner(base, strand)
    a, b, c = _full(posed), _full(candidate_owner), _full(owner_only)
    key = _key(target)
    # A newly appended owner still executes before the old nucleotide pose.
    actual = np.asarray(b[key]["backbone_position"])
    np.testing.assert_allclose(actual, _rigid(c[key]["backbone_position"], N), atol=1e-10)
    expected_motion = _rigid(a[key]["backbone_position"], M)
    gap = float(np.linalg.norm(actual - expected_motion))
    assert gap > 1.0
    # The unrelated helix is an exact native control, including its Full frames.
    other = base.helices[1].id
    assert {k: v for k, v in a.items() if k[0] == other} == {
        k: v for k, v in b.items() if k[0] == other}
    assert posed.model_dump_json() == locked
    _verify(candidate_owner)
    print(f"owner-order {direction.value}: backbone discrepancy={gap:.9f} nm")


@pytest.mark.parametrize("direction", list(m.Direction))
def test_final_pass_after_a_later_residue_delta_breaks_world_space_chronology(direction):
    source = _source()
    _, target = _target(source, direction)
    prior = _nucleotide(source, target, N, "prior-residue")
    locked = prior.model_dump_json()
    later = _nucleotide(prior, target, D, "later-world-delta", compose=True)
    a, b = _full(prior), _full(later)
    key = _key(target)
    for field in ("backbone_position", "base_position", "slab_position"):
        # Verify the native compose command is D(N(p)) before diagnosing M.
        np.testing.assert_allclose(b[key][field], _rigid(a[key][field], D), atol=1e-10)
        naive_final_pass = _rigid(b[key][field], M)          # M D N
        chronological = _rigid(_rigid(a[key][field], M), D)  # D M N
        difference = chronological - naive_final_pass
        # This gap is independently D.translation - R(M)*D.translation.
        np.testing.assert_allclose(difference, [1, -5, 0], atol=1e-10)
    assert {k: v for k, v in a.items() if k != key} == {
        k: v for k, v in b.items() if k != key}
    assert prior.model_dump_json() == locked
    _verify(later)
    print(f"final-pass-order {direction.value}: discrepancy={np.sqrt(26):.9f} nm")


def test_native_later_tail_already_uses_moved_construction_frame():
    source = _source()
    moved = _owner(source)
    # Same native producer, before and after moving its terminal construction frame.
    # No candidate tail math or reinterpreted strand polarity is introduced.
    stationary_tail = _append_extension(source, _inputs(source, modification=None))
    moved_tail = _append_extension(moved, _inputs(moved, modification=None))
    locked = moved_tail.model_dump_json()
    a, b = _full(stationary_tail), _full(moved_tail)
    tail = [key for key in b if key[0] == "__ext_owned-terminal"]
    assert len(tail) == 2 and not any(key in _full(moved) for key in tail)
    gaps = []
    for key in tail:
        actual = b[key]["backbone_position"]
        np.testing.assert_allclose(actual, _rigid(a[key]["backbone_position"], M), atol=1e-10)
        # The tail was absent at the earlier prefix, but is already in its moved
        # construction frame. A blanket late transform would move it twice.
        gaps.append(float(np.linalg.norm(_rigid(actual, M) - actual)))
    assert min(gaps) > 1.0
    assert moved_tail.model_dump_json() == locked
    _verify(moved_tail)
    print(f"later-tail double application: {min(gaps):.9f}..{max(gaps):.9f} nm")
