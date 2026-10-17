"""Complete native poses upgrade one row without recovery or adjacent inference."""

from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import crud, part_deformation_preview_sessions as host, state
from backend.api import part_proof_commands as commands
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import command_rows
from tests.test_part_deformation_preview import _append, owned_capture
from tests.test_part_deformation_preview_sessions import checkpoint, unchanged
from tests.test_part_placement_pose_commands import inputs
from tests.test_part_transform_preview import FEATURE, snapshot
from tests.test_part_transform_preview_sessions import document, opening, update, verified  # noqa: F401


def recipe(*, organized=False):
    source = create_empty_part("Complete poses", "HONEYCOMB")
    source = snapshot(source, "bundle-create", crud.BundleRequest(cells=[[0, 0], [0, 1]],
        length_bp=12, ligate_adjacent=False, history_seed=uuid4()).model_dump(mode="json"), "bundle")
    primary = source.cluster_transforms[0]
    for owner in (
        m.ClusterRigidTransform(id="linked-owner", name="Linked", helix_ids=[source.helices[1].id],
                                parent_cluster_id=primary.id),
        m.ClusterRigidTransform(id="fixed-owner", name="Fixed"),
    ):
        source = _append(source, m.ClusterCreateLogEntry(id=f"create-{owner.id}",
            cluster_id=owner.id, name=owner.name, helix_ids=owner.helix_ids,
            domain_ids=owner.domain_ids, cluster_snapshot=owner, proof_version=2))
    if organized:
        source = snapshot(source, "group-organize", {"expected_placement_ids": [
            owner.id for owner in source.cluster_transforms]}, "organize")
    source = _append(source, m.ClusterOpLogEntry(id=FEATURE, cluster_id=primary.id, proof_version=1,
        translation=[1, 2, 3], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], source="manual-linked",
        authored_fields={} if organized else {"name": "Renamed", "color": "#123456", "opacity": .5}))
    return snapshot(source, "extrude-segment", {"cells": [[8, 8]], "length_bp": 3,
        "plane": "XY", "history_seed": str(uuid4())}, "later-extrusion")


def patch_from_prepare(opened):
    # Read the actual fixed prefix supplied to the existing controls. The live
    # post-suffix owner list is deliberately not used to author this definition.
    context = opened["control_context"]
    prefix = m.Design(cluster_transforms=context["cluster_transforms"])
    definition = inputs(prefix)
    definition.pop("primary_authored_fields")
    definition.pop("legacy_source")
    return {**context["placement_upgrade"], "definition": definition}


@pytest.mark.parametrize("organized", [False, True])
def test_original_single_row_fixture_is_cold_reproducible(organized):
    source = recipe(organized=organized)
    verified(source)
    assert m.Design.model_validate_json(source.model_dump_json()) == source


@pytest.mark.parametrize("organized", [False, True])
def test_upgrade_preview_apply_cold_reload_undo_and_normal_compound_reedit(document, organized):  # noqa: F811
    source = recipe(organized=organized)
    state.load_design(source)
    before = checkpoint()
    opened = host.prepare(opening(), family="transform")
    assert opened["command_kind"] == opened["evaluated_command_kind"] == "cluster_op"
    patch = patch_from_prepare(opened)
    evaluated = host.evaluate({**update(opened, params=patch), "include_geometry": False}, family="transform")
    assert evaluated["command_kind"] == "cluster_op"
    assert evaluated["evaluated_command_kind"] == "placement-poses"
    assert evaluated["candidate"] is None
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=patch), family="transform")
    assert receipt["status"] == "applied" and receipt["command_kind"] == "cluster_op"
    assert receipt["revision"] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    candidate = state.get_or_404()
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    entry = next(row for row in candidate.feature_log if row.id == FEATURE)
    original = next(row for row in source.feature_log if row.id == FEATURE)
    assert entry.op_kind == "placement-poses"
    assert entry.params["primary_authored_fields"] == original.authored_fields
    assert entry.params["legacy_source"] == original.source
    assert candidate.feature_log[-1].id == "later-extrusion"
    for pose in patch["definition"]["poses"]:
        owner = next(owner for owner in candidate.cluster_transforms if owner.id == pose["cluster_id"])
        assert owner.translation == pose["translation"] and owner.rotation == pose["rotation"]
    verified(m.Design.model_validate_json(candidate.model_dump_json()))
    # A subsequent normal lease has the new role on both sides and no upgrade.
    fresh = host.prepare(opening(), family="transform")
    assert fresh["command_kind"] == fresh["evaluated_command_kind"] == "placement-poses"
    assert fresh["control_context"]["placement_upgrade"] is None
    changed = deepcopy(entry.params["poses"])
    changed[1]["translation"] = [8, 9, 10]
    host.apply(update(fresh, params={"poses": changed}), family="transform")
    verified(state.get_or_404())
    state.undo()
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


@pytest.mark.parametrize("failure", ["missing-owner", "changed-frame", "stale-definition"])
def test_invalid_complete_upgrade_refuses_without_mutation_or_history(document, failure):  # noqa: F811
    state.load_design(recipe())
    before = checkpoint()
    opened = host.prepare(opening(), family="transform")
    patch = patch_from_prepare(opened)
    if failure == "missing-owner":
        patch["definition"]["poses"][1]["cluster_id"] = "absent"
    elif failure == "changed-frame":
        patch["definition"]["poses"][1]["parent_cluster_id"] = None
    else:
        patch["expected_definition_sha256"] = "0" * 64
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, params=patch), family="transform")
    # Local preview/Apply draft validation uses the shared 422 contract; a
    # later full-recipe edit conflict has its separate 409 boundary.
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == {
        "missing-owner": "missing_reference", "changed-frame": "invalid_selection",
        "stale-definition": "repair_conflict"}[failure]
    unchanged(before)


def test_source_kind_cannot_be_forged_from_the_display_envelope():
    from backend.api import part_transform_preview as preview, part_transform_preview_dto as dto

    source = recipe()
    prepared = preview.prepare_from_capture(owned_capture(source), FEATURE)
    evaluated = preview.evaluate(prepared, {})
    with pytest.raises(CommandContractError):
        dto.prepare_display(prepared.copy_prefix(), evaluated, source_entry=prepared._entry,
                            envelope={"command_kind": "placement-poses"})


def test_complete_pose_contract_requires_top_level_recovery_container():
    source = recipe()
    params = inputs(source.copy_with(cluster_transforms=source.cluster_transforms[:3]))
    # Deliberately hostile in-memory input: the persisted Minor schema also
    # rejects this role. Proof must not trust bypassed model construction.
    child = m.MinorMutationLogEntry.model_construct(id="bad-child", op_subtype="placement-poses",
                                                   label="Bad container", params=params)
    source.feature_log = [m.RoutingClusterLogEntry(id="bad-row", children=[child])]
    with pytest.raises(ValueError, match="placement_poses_requires_snapshot"):
        list(command_rows(source, 128))
    assert commands.dependencies("placement-poses", params).known
