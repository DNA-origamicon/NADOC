"""Independent nonempty replay, provenance, invalidation, and bounded capture."""
from copy import deepcopy

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import ClusterRigidTransform, Design, MinorMutationLogEntry, RoutingClusterLogEntry
from backend.core.part_dependencies import Dependencies, DependencyIndex, Resource
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import import_root
from backend.core.part_verification_capture import CaptureLimit, capture


def imported_history():
    source = Design(cluster_transforms=[ClusterRigidTransform(id="cluster")])
    root = import_root(source)
    source.recipe_root = root
    commands = [
        ("joint-place", {"joint_id": "joint", "cluster_id": "cluster", "local_axis_origin": [0, 0, 0],
                         "local_axis_direction": [0, 0, 1], "_proof_version": 1}),
        ("joint-update", {"joint_id": "joint", "name": "Edited joint", "_proof_version": 1}),
    ]
    current = source
    children = []
    for kind, params in commands:
        current = execute(kind, current, params)
        children.append(MinorMutationLogEntry(op_subtype=kind, label=kind, params=params))
    current.feature_log = [RoutingClusterLogEntry(children=children)]
    return current


def verify(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_imported_nonempty_history_replays_without_recovery_payloads():
    design = imported_history()
    before = design.model_dump()
    result = verify(design)
    assert result["status"] == "reproduced_import"
    assert not result["native_editable"]
    assert result["checked_commands"] == 2
    first, second = design.feature_log[0].children
    assert result["dependencies"]["parents"][second.id] == [first.id]
    assert design.model_dump() == before
    assert verify(Design.model_validate_json(design.model_dump_json())) == result


def test_modified_root_bytes_cannot_keep_old_provenance_hash():
    design = imported_history()
    design.recipe_root = design.recipe_root.model_copy(update={"source_json": design.recipe_root.source_json + " "})
    assert verify(design)["issues"][0]["code"] == "invalid_recipe_root"


def test_saved_output_cannot_cover_up_unlogged_authoring_change():
    design = imported_history()
    design.cluster_joints[0].name = "Unlogged alteration"
    design.feature_log[0].post_state_gz_b64 = "matching-output-is-not-proof"
    result = verify(design)
    assert result["status"] == "mismatch"
    assert result["issues"][0]["fields"] == ["cluster_joints"]


def test_deleting_parent_command_fails_on_unresolved_joint():
    design = imported_history()
    design.feature_log[0].children.pop(0)
    result = verify(design)
    assert result["status"] == "failed"
    assert result["issues"][0]["code"] == "command_failed"


def test_possible_impact_is_not_reported_as_proven_blockage():
    design = imported_history()
    first, second = design.feature_log[0].children

    def fail(*args):
        raise ValueError("Cannot construct first feature")

    result = assess_part_history(design, execute=fail, dependencies=dependencies)
    issue = result["issues"][0]
    assert issue["feature_id"] == first.id
    assert issue["possible_dependents"] == [second.id]
    assert "blocked" not in issue


@pytest.mark.parametrize("kind,params,path", [
    ("nick-batch", {"nicks": [{"helix_id": "missing", "bp_index": 2,
                               "direction": "FORWARD"}]}, ["nicks", 0, "helix_id"]),
    ("loop-skip-clear", {"helix_ids": ["missing"], "plane_a_bp": 0,
                         "plane_b_bp": 5}, ["helix_ids", 0]),
])
def test_reproducible_noop_with_missing_selection_is_not_verified(kind, params, path):
    from backend.core.part_history_contract import create_empty_part

    design = create_empty_part("Broken", "SQUARE")
    child = MinorMutationLogEntry(op_subtype=kind, label=kind, params={**params, "_proof_version": 1})
    design.feature_log = [RoutingClusterLogEntry(children=[child])]
    result = verify(design)
    assert result["status"] == "failed"
    assert not result["native_editable"]
    issue = result["issues"][0]
    assert issue["code"] == "missing_reference"
    assert issue["feature_id"] == child.id
    assert issue["kind"] == kind
    assert issue["references"][0]["identity"] == "missing"
    assert issue["references"][0]["parameter_path"] == path


def test_unknown_command_version_does_not_use_legacy_replay():
    design = imported_history()
    design.feature_log[0].children[0].params["_proof_version"] = 999
    assert verify(design)["status"] == "unverified"


def test_fingerprints_track_recipe_and_authoring_independently():
    design = imported_history()
    original = verify(design)
    design.metadata.name = "unlogged edit"
    changed = verify(design)
    assert original["recipe_fingerprint"] == changed["recipe_fingerprint"]
    assert original["authoring_fingerprint"] != changed["authoring_fingerprint"]
    design.feature_log[0].children[1].params["name"] = "Different command"
    assert verify(design)["recipe_fingerprint"] != original["recipe_fingerprint"]


def test_capture_skips_large_recovery_payloads_and_preserves_proof():
    design = imported_history()
    design.feature_log[0].post_state_gz_b64 = "x" * 3_000_000
    isolated = capture(design)
    assert isolated.feature_log[0].post_state_gz_b64 == ""
    assert verify(isolated) == verify(design)
    isolated.feature_log[0].children[0].params["joint_id"] = "other"
    assert design.feature_log[0].children[0].params["joint_id"] == "joint"


def test_capture_rejects_over_budget_input_without_mutation():
    design = imported_history()
    before = deepcopy(design)
    with pytest.raises(CaptureLimit):
        capture(design, max_nodes=2)
    with pytest.raises(CaptureLimit):
        capture(design, max_bytes=2)
    with pytest.raises(CaptureLimit):
        capture(design, seconds=0)
    assert design == before


def test_typed_dependencies_do_not_conflate_equal_ids_and_support_suffix_invalidation():
    index = DependencyIndex()
    helix, strand = Resource("helix", "same"), Resource("strand", "same")
    index.append("helix-create", Dependencies(writes=frozenset({helix})))
    index.append("strand-create", Dependencies(writes=frozenset({strand})))
    index.append("helix-edit", Dependencies(reads=frozenset({helix})))
    assert index.affected(["helix-create"]) == {"helix-create", "helix-edit"}
    index.invalidate_from(2)
    index.append("strand-edit", Dependencies(reads=frozenset({strand})))
    assert index.affected(["helix-create"]) == {"helix-create"}
    assert index.affected(["strand-create"]) == {"strand-create", "strand-edit"}


def test_unknown_dependency_is_a_barrier_not_an_independence_claim():
    index = DependencyIndex()
    index.append("before", Dependencies())
    index.append("unknown", Dependencies(known=False))
    index.append("after", Dependencies())
    assert index.affected(["before"]) == {"before", "unknown", "after"}
    assert not index.complete


def test_native_joint_recording_persists_the_contract_version():
    from backend.api import state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.api.routes_cluster_joints import _build_add_joint
    token = set_current_doc("joint-proof-recording-test")
    try:
        source = Design(cluster_transforms=[ClusterRigidTransform(id="cluster")])
        source.recipe_root = import_root(source)
        state.load_design(source)
        params = {"joint_id": "joint", "cluster_id": "cluster", "local_axis_origin": [0, 0, 0],
                  "local_axis_direction": [0, 0, 1]}
        state.mutate_with_minor_log(op_subtype="joint-place", label="Joint", params=params,
                                    fn=lambda d: _build_add_joint(d, params))
        assert "_proof_version" not in params
        result = verify(state.get_or_404())
        assert result["status"] == "reproduced_import"
        assert result["checked_commands"] == 1
    finally:
        state.close_session()
        reset_current_doc(token)
