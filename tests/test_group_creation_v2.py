"""Grouping v2 retains placement identities; saved v1 keeps exact old effects.

Tiny memory-only contracts. Recovery bytes are not replay authority, and these
tests do not modify the numerical engines or assert new molecular placement.
"""

from copy import deepcopy
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api import doc_context, routes_clusters, state
from backend.api.generated_commands import certify_entries
from backend.api.generated_history import GeneratedHistory
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import is_versioned, supports_recipe_edit
from backend.core.models import (
    ClusterCreateLogEntry, ClusterJoint, ClusterRigidTransform, Design, DomainRef,
)
from backend.core.part_history_contract import assess_part_history
from backend.core.part_overlay_commands import build, command_input, edit_entry
from backend.core.two_np_generator import GeneratorSettings
from tests.test_part_deformation_preview import _append, native_source


def source():
    design = native_source()
    return design.copy_with(feature_log=design.feature_log[:-1], deformations=[])


def grouping(design):
    return ClusterRigidTransform(id=str(uuid4()), name="All helices",
                                 helix_ids=[helix.id for helix in design.helices])


def arguments(group, version=2):
    return {"cluster": group.model_dump(mode="json"), "_proof_version": version}


def row(group, version=2):
    return ClusterCreateLogEntry(cluster_id=group.id, name=group.name,
        helix_ids=group.helix_ids, cluster_snapshot=group, proof_version=version)


def test_v2_retains_all_existing_identities_pose_metadata_and_order_when_default_empties():
    original = source()
    owner = original.cluster_transforms[0].model_copy(update={
        "translation": [2., 3., 4.], "pivot": [1., 2., 3.], "color": "#123456", "opacity": .6,
    })
    independent = ClusterRigidTransform(id="independent-empty", name="Empty user group")
    second_default = ClusterRigidTransform(id="empty-default", is_default=True, auto_created=True)
    original = original.copy_with(cluster_transforms=[owner, independent, second_default])
    before = original.model_dump(mode="json")
    group = grouping(original)
    candidate = build("cluster_create", original, arguments(group))
    assert [cluster.id for cluster in candidate.cluster_transforms] == [owner.id, independent.id, second_default.id, group.id]
    assert candidate.cluster_transforms[0] == owner.model_copy(update={"helix_ids": []})
    assert candidate.cluster_transforms[1:3] == [independent, second_default]
    assert candidate.lattice_frames == original.lattice_frames
    assert original.model_dump(mode="json") == before
    assert Design.model_validate_json(candidate.model_dump_json()) == candidate


def test_v1_and_unmarked_build_keep_the_exact_legacy_output():
    original = source()
    group = grouping(original)
    expected = original.copy_with(cluster_transforms=[group]).model_dump_json()
    for params in (arguments(group, 1), {"cluster": group.model_dump(mode="json")}):
        candidate = build("cluster_create", original, params)
        assert candidate.model_dump_json() == expected
        with pytest.raises(ValidationError, match="placement cluster is missing"):
            Design.model_validate_json(candidate.model_dump_json())


@pytest.mark.parametrize("version", [None, True, 0, 3, "2", 2.0])
def test_unsupported_explicit_group_versions_are_rejected_before_building(version):
    original = source()
    params = arguments(grouping(original), version)
    assert not dependencies("cluster_create", params).known
    with pytest.raises(ValueError, match="version"):
        build("cluster_create", original, params)


@pytest.mark.parametrize("kind", ["cluster_op", "deformation", "bundle-create"])
def test_group_v2_does_not_upgrade_other_command_families(kind):
    assert not dependencies(kind, {"_proof_version": 2}).known


def test_capabilities_advertise_local_group_versions_without_global_upgrade():
    from backend.api.part_proof_commands import capabilities

    result = capabilities()
    assert result["proof_version"] == 1
    assert result["proof_version_overrides"] == {
        "cluster_create": {"supported": [1, 2], "authoring": 2},
    }


def test_empty_parent_joint_and_frame_references_survive_without_retargeting():
    original = source()
    owner = original.cluster_transforms[0]
    child = ClusterRigidTransform(id="child", parent_cluster_id=owner.id,
        helix_ids=[original.helices[0].id],
        domain_ids=[DomainRef(strand_id=original.strands[0].id, domain_index=0)])
    joint = ClusterJoint(id="joint", cluster_id=owner.id)
    original = original.copy_with(cluster_transforms=[owner, child], cluster_joints=[joint])
    candidate = build("cluster_create", original, arguments(grouping(original)))
    assert candidate.cluster_transforms[0].id == owner.id
    assert candidate.cluster_transforms[0].helix_ids == []
    assert candidate.cluster_transforms[1] == child
    assert candidate.cluster_joints == [joint]
    assert candidate.lattice_frames == original.lattice_frames
    assert Design.model_validate_json(candidate.model_dump_json()) == candidate


def test_retained_empty_owner_does_not_change_native_candidate_nucleotide_geometry():
    from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_positions

    original = source()
    group = grouping(original).model_copy(update={"translation": [3., 4., 5.]})
    legacy = build("cluster_create", original, arguments(group, 1))
    current = build("cluster_create", original, arguments(group, 2))
    assert deformed_helix_axes(current) == deformed_helix_axes(legacy)
    for helix in original.helices:
        before = deformed_nucleotide_positions(helix, legacy)
        after = deformed_nucleotide_positions(helix, current)
        assert len(after) == len(before)
        for left, right in zip(before, after, strict=True):
            for field in ("position", "base_position", "base_normal", "axis_tangent"):
                np.testing.assert_array_equal(getattr(left, field), getattr(right, field))


def test_frame_append_can_refill_the_same_empty_placement_owner():
    from backend.core.lattice_frames import append_frame_bundle

    original = source()
    candidate = build("cluster_create", original, arguments(grouping(original)))
    frame = candidate.lattice_frames[0]
    extended = append_frame_bundle(candidate, frame.id, [[2, 2]], 7, plane=frame.plane)
    owner = next(cluster for cluster in extended.cluster_transforms if cluster.id == frame.placement_cluster_id)
    assert owner.helix_ids == [extended.helices[-1].id]
    assert extended.cluster_transforms[1:] == candidate.cluster_transforms[1:]
    assert extended.lattice_frames == original.lattice_frames
    assert Design.model_validate_json(extended.model_dump_json()) == extended


def test_native_group_v2_roundtrips_replays_and_edits_without_cached_outputs():
    original = source()
    entry = row(grouping(original))
    candidate = _append(original, entry)
    restored = Design.model_validate_json(candidate.model_dump_json())
    assert is_versioned(restored.feature_log[-1])
    assert supports_recipe_edit(restored, restored.feature_log[-1])
    result = assess_part_history(restored, execute=execute, dependencies=dependencies)
    assert result["status"] == "verified", result
    edited = edit_entry(entry, {"name": "Renamed group"}, prefix=original)
    assert edited.id == entry.id and edited.cluster_id == entry.cluster_id
    assert command_input(edited)[1]["_proof_version"] == 2
    assert build("cluster_create", original, command_input(edited)[1]).cluster_transforms[0].id == original.cluster_transforms[0].id


def test_ordinary_all_members_group_records_v2_with_one_undo_and_valid_serialized_state():
    original = source()
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(f"group-v2-{uuid4()}")
    try:
        state.load_design(original)
        revision, depth = state.revision(), state.undo_depth()
        routes_clusters.add_cluster(routes_clusters.AddClusterBody(
            name="All helices", helix_ids=[helix.id for helix in original.helices]))
        candidate = state.get_or_404()
        assert candidate.feature_log[-1].proof_version == 2
        assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
        assert Design.model_validate_json(candidate.model_dump_json()) == candidate
        report = assess_part_history(candidate, execute=execute, dependencies=dependencies)
        assert report["status"] == "verified", report
        state.undo()
        assert state.get_or_404().model_dump(mode="json") == original.model_dump(mode="json")
    finally:
        try:
            state.close_session()
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(request_revision)
            doc_context.set_request_feature_log_entry_id(request_entry)


@pytest.mark.parametrize("version", [1, 2])
def test_generated_overlay_recording_and_certification_preserve_the_actual_version(version):
    original = source()
    # Partial grouping gives a valid v1 source too, allowing both actual versions
    # through independent certification without normalizing their markers.
    group = grouping(original).model_copy(update={"helix_ids": [original.helices[0].id]})
    params = arguments(group, version)
    candidate = build("cluster_create", original, params)
    history = GeneratedHistory(original, GeneratorSettings())
    history.record(original, candidate, "cluster_create", "Group", params, "group", scoped=False)
    entry = history.design.feature_log[-1]
    assert entry.proof_version == version
    assert command_input(entry)[1]["_proof_version"] == version
    certified, reason = certify_entries(original, candidate, [entry])
    assert reason is None
    assert certified[0].proof_version == version
    assert history.design.model_dump(mode="json") == candidate.copy_with(
        feature_log=[*original.feature_log, entry]).model_dump(mode="json")


def test_generated_v2_scoped_recording_preserves_labels_equal_to_resource_ids():
    original = source()
    group = grouping(original).model_copy(update={"name": original.helices[0].id})
    params = arguments(group)
    candidate = build("cluster_create", original, params)
    history = GeneratedHistory(original.copy_with(helices=[], strands=[], cluster_transforms=[], lattice_frames=[], feature_log=[]), GeneratorSettings())
    # Real generated sources are composed before the overlay. Seed that private
    # namespace using the same typed mapper, never the legacy string walker.
    from backend.core.part_scope_references import namespace_design
    history.design = namespace_design(original, history.group_id, history.source_ids)
    history.record(original, candidate, "cluster_create", "Group", params, "group")
    assert history.design.feature_log[-1].proof_version == 2
    assert history.design.feature_log[-1].name == original.helices[0].id


def test_v2_namespaced_group_without_owner_bootstraps_stably_but_v1_still_refuses():
    from backend.core.part_scope_references import namespace_design

    original = source()
    # A valid unframed source can have DNA before any placement owner exists.
    original = original.copy_with(
        cluster_transforms=[], lattice_frames=[], feature_log=[],
        helices=[helix.model_copy(update={"lattice_frame_id": None}) for helix in original.helices],
    )
    named = namespace_design(original.copy_with(cluster_transforms=[grouping(original)]),
                             str(uuid4()), set())
    group = named.cluster_transforms[0]
    scoped = named.copy_with(cluster_transforms=[])
    before = scoped.model_dump_json()
    first = build("cluster_create", scoped, arguments(group, 2))
    second = build("cluster_create", scoped, arguments(group, 2))
    assert first.model_dump_json() == second.model_dump_json()
    assert first.cluster_transforms[-1] == group
    assert len(first.cluster_transforms) == 2
    assert first.cluster_transforms[0].is_default
    assert first.cluster_transforms[0].helix_ids == []
    assert first.cluster_transforms[0].id != group.id
    assert Design.model_validate_json(first.model_dump_json()) == first
    assert scoped.model_dump_json() == before
    for params in (arguments(group, 1), {"cluster": group.model_dump(mode="json")}):
        with pytest.raises(ValueError, match="UUID"):
            build("cluster_create", scoped, params)


def test_v2_uuid_group_uses_the_existing_default_owner_identity_factory():
    from backend.core.feature_identity import identity_factory

    original = source().copy_with(cluster_transforms=[], lattice_frames=[])
    original = original.copy_with(helices=[
        helix.model_copy(update={"lattice_frame_id": None}) for helix in original.helices])
    group = grouping(original).model_copy(update={"helix_ids": [original.helices[0].id]})
    legacy = build("cluster_create", original, arguments(group, 1))
    current = build("cluster_create", original, arguments(group, 2))
    expected = identity_factory(group.id)("cluster", [helix.id for helix in original.helices])
    assert legacy.cluster_transforms[0].id == current.cluster_transforms[0].id == expected
    assert current.model_dump_json() == legacy.model_dump_json()


def test_registered_batch_emits_group_v2_and_publication_scope_accepts_it():
    from backend.api.part_batch_publication_scope import admit_batch_source
    from tests.test_part_registered_batch import prepare

    result = prepare()
    candidate = result["candidate"]
    group = next(entry for entry in candidate.feature_log if entry.feature_type == "cluster_create")
    assert group.proof_version == 2
    before = deepcopy(candidate.model_dump(mode="json"))
    admit_batch_source(candidate)
    assert candidate.model_dump(mode="json") == before


def test_generated_unversioned_nick_still_promotes_to_native_routing():
    original = source()
    domain = original.strands[0].domains[0]
    params = {"helix_id": domain.helix_id, "direction": domain.direction.value,
              "bp_index": min(domain.start_bp, domain.end_bp) + 2}
    candidate = execute("nick", original, {**params, "_proof_version": 1})
    history = GeneratedHistory(original, GeneratorSettings())
    history.record(original, candidate, "nick", "Nick", params, "nick", scoped=False)
    entry = history.design.feature_log[-1]
    assert entry.feature_type == "routing-cluster"
    assert len(entry.children) == 1
    assert entry.children[0].params["_proof_version"] == 1
    assert not history.unverified_steps
    report = assess_part_history(history.design, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
