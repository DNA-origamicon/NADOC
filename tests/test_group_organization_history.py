"""Private organization history remains editable and chronologically recoverable.

No active document is installed. Native inputs, recovery strings and derived
geometry stay in memory; public organization activation is a separate gate.
"""

import pytest

from backend.api import crud, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change
from backend.core import models as m
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import command_rows
from backend.core.part_overlay_commands import command_input
from backend.core.part_verification_capture import capture
from tests.test_group_organization_commands import group, organize, source


def _append(design, entry):
    kind, params = command_input(entry)
    result = execute(kind, design, params)
    if entry.feature_type == "snapshot":
        pre, pre_size = state.encode_design_snapshot(design)
        post, post_size = state.encode_design_snapshot(result)
        entry = entry.model_copy(update={
            "design_snapshot_gz_b64": pre, "snapshot_size_bytes": pre_size,
            "post_state_gz_b64": post, "post_state_size_bytes": post_size})
    return result.copy_with(id=design.id, recipe_root=design.recipe_root,
        feature_log=[*design.feature_log, entry])


def history(*, padding=0):
    design = create_empty_part("Organization chronology", "HONEYCOMB")
    params = crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=12,
        name="Organization chronology", history_seed="9837593d-dcca-4609-aa75-878dd522144e").model_dump(mode="json")
    design = _append(design, m.SnapshotLogEntry(id="bundle", op_kind="bundle-create",
        label="Bundle", params={**params, "_proof_version": 1}))
    placement = m.ClusterRigidTransform(id="placement", name="Arm",
        helix_ids=[design.helices[0].id], color="#abcdef")
    design = _append(design, m.ClusterCreateLogEntry(id="placement-create",
        cluster_id=placement.id, name=placement.name, helix_ids=placement.helix_ids,
        cluster_snapshot=placement, proof_version=2))
    design = _append(design, m.ClusterOpLogEntry(id="placement-pose",
        cluster_id=placement.id, proof_version=1, translation=[2, -1, 3],
        rotation=[0, 0, 0.6, 0.8], pivot=[1, 0, 0]))
    states = {2: design}
    commands = [
        ("group-organize", organize(design)),
        ("group-dissolve", {"_proof_version": 1, "group_ids": [placement.id]}),
        ("group-create", {"_proof_version": 1, "group": group(
            helix_ids=[helix.id for helix in design.helices])}),
        ("group-update", {"_proof_version": 1, "group_id": "regrouped",
            "fields": {"name": "Selected domains", "helix_ids": [],
                "domain_ids": [{"strand_id": design.strands[0].id, "domain_index": 0}],
                "color": "#123456", "opacity": 0.4}}),
    ]
    for index, (kind, inputs) in enumerate(commands, start=3):
        design = _append(design, m.SnapshotLogEntry(id=f"row-{index}", op_kind=kind,
            label=kind, params=inputs))
        states[index] = design
    for offset in range(padding):
        index = len(design.feature_log)
        design = _append(design, m.SnapshotLogEntry(id=f"padding-{offset}",
            op_kind="group-update", label="Later group label",
            params={"_proof_version": 1, "group_id": "regrouped",
                "fields": {"name": f"Later label {offset}"}}))
        states[index] = design
    return design, states


def _poison(design):
    private = m.Design.model_validate_json(design.model_dump_json())
    for entry in private.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = "not a pre-state"
            entry.post_state_gz_b64 = "not a post-state"
    return private


def _verified(design):
    report = assess_part_history(_poison(design), execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    assert report["native_editable"] is True
    assert report["checked_commands"] == len(design.feature_log)


def _edit(source, index, patch):
    private = _poison(source)
    return prepare_change(private, capture(private, preserve_entry_types=True),
        index, lambda: None, params=patch)[0]


def test_upstream_native_pose_edit_regenerates_organization_without_resurrecting_wrapper():
    design, _ = history()
    original = design.model_dump(mode="json")
    _verified(design)
    current = _edit(design, 2, {"translation": [5, 2, -1]})
    assert [entry.id for entry in current.feature_log] == [entry.id for entry in design.feature_log]
    assert current.group_organization == design.group_organization
    assert "placement" not in {item.id for item in current.group_organization.groups}
    assert next(item for item in current.cluster_transforms if item.id == "placement").translation == [5, 2, -1]
    expected = execute("cluster_op", design, {"_proof_version": 1,
        "cluster_id": "placement", "translation": [5, 2, -1],
        "rotation": [0, 0, 0.6, 0.8], "pivot": [1, 0, 0]})
    assert current.cluster_transforms == expected.cluster_transforms
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(design)
    assert deformed_helix_axes(current) == deformed_helix_axes(expected)
    assert design.model_dump(mode="json") == original
    _verified(m.Design.model_validate_json(current.model_dump_json()))
    # Regeneration repairs the selected snapshots from inputs; old poisoned
    # output strings cannot survive as the new chronology's recovery evidence.
    recovered = state.decode_design_snapshot(current.feature_log[-1].post_state_gz_b64)
    assert recovered.group_organization == current.group_organization
    assert recovered.cluster_transforms == current.cluster_transforms


def test_organization_input_edit_changes_selection_without_touching_placement_or_geometry():
    design, _ = history()
    fields = {"name": "Regroup the other helix", "helix_ids": [design.helices[1].id],
              "domain_ids": [], "opacity": 0.75, "color": "#fedcba"}
    current = _edit(design, 6, {"fields": fields})
    assert current.feature_log[-1].params["fields"] == fields
    selected = next(item for item in current.group_organization.groups if item.id == "regrouped")
    assert selected.helix_ids == [design.helices[1].id] and selected.domain_ids == []
    assert selected.name == fields["name"] and selected.opacity == fields["opacity"]
    assert current.cluster_transforms == design.cluster_transforms
    assert _geometry_for_design(current) == _geometry_for_design(design)
    assert deformed_helix_axes(current) == deformed_helix_axes(design)
    _verified(m.Design.model_validate_json(current.model_dump_json()))


def test_creator_parameter_edit_cannot_replace_authored_group_output_identity():
    design, _ = history()
    changed = dict(design.feature_log[5].params["group"], id="replacement-id", name="New label")
    current = _edit(design, 5, {"group": changed})
    assert current.feature_log[5].params["group"]["id"] == "regrouped"
    assert current.feature_log[5].params["group"]["name"] == "New label"
    assert [item.id for item in current.group_organization.groups] == [
        item.id for item in design.group_organization.groups]
    assert current.cluster_transforms == design.cluster_transforms
    _verified(current)


@pytest.mark.parametrize("optimized", [False, True], ids=["ordinary", "optimized"])
def test_recovery_seek_restores_organization_at_each_native_history_boundary(optimized):
    # The optimized payload scan is used only at >=32 rows. These are real
    # native edits with real recovery strings, not synthetic length padding.
    design, states = history(padding=26 if optimized else 0)
    assert len(design.feature_log) == (33 if optimized else 7)
    current = m.Design.model_validate_json(design.model_dump_json())
    original = design.model_dump(mode="json")
    final_position = len(design.feature_log) - 1
    for position in [-2, -1, 2, 3, 4, 5, 6, final_position, 4, 2, 5, -2, -1]:
        current = crud._seek_feature_log(current, position, optimized=optimized)
        if position == -2:
            # F0 must leave the new regime and remove rendered construction.
            # Legacy seek may retain empty default-placement metadata; this
            # assertion does not qualify or change that older recovery policy.
            assert current.group_organization is None
            assert current.helices == current.strands == []
            assert _geometry_for_design(current) == deformed_helix_axes(current) == []
        else:
            expected = states[final_position if position == -1 else position]
            assert current.group_organization == expected.group_organization
            assert current.cluster_transforms == expected.cluster_transforms
            assert _geometry_for_design(current) == _geometry_for_design(expected)
            assert deformed_helix_axes(current) == deformed_helix_axes(expected)
        current = m.Design.model_validate_json(current.model_dump_json())
    assert design.model_dump(mode="json") == original
    _verified(current)


def test_topology_substitution_keeps_live_pose_but_restores_selected_organization_snapshot():
    design, states = history()
    moved = design.copy_with(cluster_transforms=[
        item.model_copy(update={"translation": [9, 8, 7]}) if item.id == "placement" else item
        for item in design.cluster_transforms])
    for position in (2, 3, 4, 5, 6):
        selected = crud._topology_substitute(moved, states[position])
        assert selected.group_organization == states[position].group_organization
        assert selected.cluster_transforms == moved.cluster_transforms
    assert moved.group_organization == design.group_organization


@pytest.mark.parametrize("empty_placement", [False, True], ids=["no-placement", "empty-auto-placement"])
def test_active_empty_organization_never_triggers_response_time_default_repair(monkeypatch, empty_placement):
    from backend.core.part_group_model import GroupOrganization

    design = source().copy_with(group_organization=GroupOrganization(groups=[]),
        cluster_transforms=([m.ClusterRigidTransform(id="native-empty", is_default=True,
            auto_created=True)] if empty_placement else []))
    original = design.model_dump(mode="json")

    def unexpected(*args, **kwargs):
        raise AssertionError("An explicit organization must not be normalized or published by response formatting")

    monkeypatch.setattr("backend.core.cluster_autodetect.repair_empty_auto_clusters", unexpected)
    monkeypatch.setattr("backend.core.cluster_autodetect.with_default_cluster", unexpected)
    monkeypatch.setattr(state, "set_design_silent", unexpected)
    assert crud._ensure_default_cluster(design) is design
    assert design.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", ["group-organize", "group-create", "group-update", "group-dissolve"])
def test_group_commands_are_top_level_features_never_fine_routing_children(kind):
    # Unsafe construction represents a malformed retained Python object. The
    # ordinary persisted MinorOpSubtype schema already excludes these kinds;
    # the proof reader must enforce its boundary independently as well.
    child = m.MinorMutationLogEntry.model_construct(id="invalid-child",
        op_subtype=kind, label="Invalid nested group", params={"_proof_version": 1})
    row = m.RoutingClusterLogEntry.model_construct(id="routing", label="Routing", children=[child])
    design = source().copy_with(feature_log=[row])
    with pytest.raises(ValueError, match="group|organiz|top.level"):
        list(command_rows(design, 2_000))
