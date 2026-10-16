"""Named organization edits use owned feature prefixes, never latest membership.

Tiny native recipes and geometry only; no host, files, publication or UI claims.
"""

from copy import deepcopy

import pytest

from backend.api import part_deformation_preview as preview
from backend.api.part_proof_commands import execute
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.part_overlay_commands import command_input, edit_entry
from tests.test_part_deformation_preview import _append, authoring, native_source, owned_capture


def _snapshot(source, kind, **params):
    return _append(source, m.SnapshotLogEntry(
        op_kind=kind, label=kind, params={"_proof_version": 1, **params},
        design_snapshot_gz_b64="unused-recovery", post_state_gz_b64="unused-recovery",
    ))


def named_source(kind="twist"):
    original = native_source(kind)
    source = original.copy_with(deformations=[], feature_log=original.feature_log[:-1])
    placement_id = source.cluster_transforms[0].id
    source = _snapshot(source, "group-organize", expected_placement_ids=[
        item.id for item in source.cluster_transforms])
    source = _snapshot(source, "group-update", group_id=placement_id,
                       fields={"helix_ids": [source.helices[0].id]})
    strand = next(item for item in source.strands if item.domains[0].helix_id == source.helices[1].id)
    source = _snapshot(source, "group-create", group={
        "id": "other", "name": "Other domain", "helix_ids": [],
        "domain_ids": [{"strand_id": strand.id, "domain_index": 0}],
    })
    source = _snapshot(source, "group-create", group={"id": "discarded", "name": "Disposable"})
    source = _snapshot(source, "group-dissolve", group_ids=["discarded"])
    op = original.deformations[-1].model_copy(update={
        "targets": [{"kind": "part_group", "id": placement_id}],
        "target_ranges": None, "cluster_ids": [placement_id],
        "affected_helix_ids": [],
    })
    entry = original.feature_log[-1].model_copy(update={"op_snapshot": op})
    source = _append(source, entry)
    source.feature_log[-1] = entry.model_copy(update={"op_snapshot": source.deformations[-1]})
    return source


def _prepared(kind="twist"):
    source = named_source(kind)
    return source, preview.prepare_from_capture(owned_capture(source), "edited-feature")


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_named_preview_replays_all_organization_commands_and_matches_native_edit(kind):
    source, prepared = _prepared(kind)
    original = source.model_dump(mode="json")
    prefix = prepared.copy_prefix()
    patch = {"targets": [{"kind": "part_group", "id": "other"}]}
    expected_entry = source.feature_log[-1].model_copy(update={
        "op_snapshot": source.deformations[-1].model_copy(update=deepcopy(patch))})
    command, inputs = command_input(expected_entry)
    expected = execute(command, prefix, inputs)
    expected_authoring = authoring(expected)
    result = preview.evaluate(prepared, patch)
    assert authoring(result.design) == expected_authoring
    assert result.entry.op_snapshot.targets == patch["targets"]
    assert result.entry.op_snapshot.cluster_ids == source.deformations[-1].cluster_ids
    assert result.entry.op_snapshot.affected_helix_ids == [source.helices[1].id]
    assert result.entry.op_snapshot.target_ranges[0].strand_id is not None
    assert source.model_dump(mode="json") == original
    # Returned controls, candidate and request must not alias the retained prefix.
    prefix.group_organization.groups.clear()
    patch["targets"][0]["id"] = "missing"
    result.design.group_organization.groups.clear()
    again = preview.evaluate(prepared, {"targets": [{"kind": "part_group", "id": "other"}]})
    assert authoring(again.design) == expected_authoring


def test_later_group_edit_never_changes_prepared_feature_selection(monkeypatch):
    source = named_source()
    target = source.deformations[-1].targets[0]["id"]
    source = _snapshot(source, "group-update", group_id=target,
                       fields={"helix_ids": [source.helices[1].id]})
    actual = preview.execute

    def prefix_only(kind, design, params):
        assert not (kind == "group-update" and params.get("fields", {}).get("helix_ids") == [source.helices[1].id])
        return actual(kind, design, params)

    monkeypatch.setattr(preview, "execute", prefix_only)
    prepared = preview.prepare_from_capture(owned_capture(source), "edited-feature")
    evaluated = preview.evaluate(prepared, {})
    assert evaluated.entry.op_snapshot.affected_helix_ids == [source.helices[0].id]
    assert evaluated.source_equivalence_checked is False and evaluated.downstream_evaluated is False


@pytest.mark.parametrize("targets", [
    [], None, [{"kind": "strand", "id": "other"}],
    [{"kind": "part_group", "id": "other"}, {"kind": "strand", "id": "other"}],
    [{"kind": "part_group", "id": "other"}] * 2,
    [{"kind": "part_group", "id": True}],
    [{"kind": "part_group", "id": "other", "placement_id": "other"}],
])
def test_named_edit_rejects_empty_mixed_or_malformed_replacement_atomically(targets):
    source = named_source()
    entry = source.feature_log[-1]
    before = source.model_dump(mode="json")
    with pytest.raises(CommandContractError):
        edit_entry(entry, {"targets": targets}, prefix=source)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("failure", ["missing", "empty", "placement_alias", "no_prefix"])
def test_named_edit_never_falls_back_to_placement_or_global_scope(failure):
    source = named_source()
    prefix = source.copy_with(deformations=[])
    target = "other"
    if failure == "missing":
        target = "missing"
    elif failure == "empty":
        prefix.group_organization.groups[-1] = prefix.group_organization.groups[-1].model_copy(
            update={"domain_ids": [], "helix_ids": []})
    elif failure == "placement_alias":
        target = source.cluster_transforms[0].id
        prefix = prefix.copy_with(group_organization=prefix.group_organization.model_copy(
            update={"groups": [g for g in prefix.group_organization.groups if g.id != target]}))
    else:
        prefix = None
    before = source.model_dump(mode="json")
    with pytest.raises(CommandContractError):
        edit_entry(source.feature_log[-1], {"targets": [{"kind": "part_group", "id": target}]}, prefix=prefix)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("targets", [None, [{"kind": "domain", "strand_id": "s", "domain_index": 0}],
    [{"kind": "part_group", "id": "other"}, {"kind": "strand", "id": "s"}]])
def test_new_named_edit_does_not_unlock_legacy_or_mixed_target_scope(targets):
    source = named_source()
    entry = source.feature_log[-1].model_copy(update={"op_snapshot": source.deformations[-1].model_copy(
        update={"targets": targets})})
    with pytest.raises(CommandContractError):
        edit_entry(entry, {"targets": [{"kind": "part_group", "id": "other"}]}, prefix=source)


def test_named_edit_preserves_separate_numerical_placement_context():
    source = named_source()
    with pytest.raises(CommandContractError):
        edit_entry(source.feature_log[-1], {"targets": [{"kind": "part_group", "id": "other"}],
            "cluster_ids": []}, prefix=source)


def test_named_capability_is_bounded_schema_only_and_can_repair_missing_identity():
    from backend.core.part_deformation_edit import can_edit_named_groups

    operation = named_source().deformations[-1].model_copy(update={
        "targets": [{"kind": "part_group", "id": "missing-but-repairable"}]})
    assert can_edit_named_groups(operation)
    assert not can_edit_named_groups(operation.model_copy(update={"targets": []}))

    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("Unreviewed or oversized list must refuse before iteration")

    assert not can_edit_named_groups(operation.model_copy(update={"targets": Unvisited([None] * 10_001)}))


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_named_display_controls_and_native_geometry_remain_complete_and_owned(kind):
    from backend.api import part_deformation_preview_dto as dto
    from backend.core.design_geometry import _geometry_for_design

    source, prepared = _prepared(kind)
    prefix = prepared.copy_prefix()
    evaluated = preview.evaluate(prepared, {"targets": [{"kind": "part_group", "id": "other"}]})
    packet = dto.prepare_display(prefix, evaluated)
    context = packet["control_context"]
    assert context["group_organization"] == prefix.group_organization.model_dump(mode="json")
    assert context["capabilities"]["change_targets"] is True
    assert context["capabilities"]["change_clusters"] is False
    assert context["selected_operation"] == evaluated.entry.op_snapshot.model_dump(mode="json")
    assert unpack_records(packet["candidate"]["nucleotides"]) == _geometry_for_design(evaluated.design)
    context["group_organization"]["groups"].clear()
    assert prefix.group_organization.groups and source.group_organization.groups


def test_named_controls_only_uses_evaluated_ranges_without_geometry_or_second_resolution(monkeypatch):
    from backend.api import part_deformation_preview_dto as dto
    from backend.core import deformation, deformation_scope, design_geometry, part_group_selection

    _source, prepared = _prepared()
    evaluated = preview.evaluate(prepared, {"targets": [{"kind": "part_group", "id": "other"}]})

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Owned evaluated ranges suffice; no geometry or re-resolution")

    monkeypatch.setattr(design_geometry, "_geometry_for_design", forbidden)
    monkeypatch.setattr(deformation, "deformed_helix_axes", forbidden)
    monkeypatch.setattr(deformation_scope, "resolve_deformation_targets", forbidden)
    monkeypatch.setattr(part_group_selection, "resolve_deformation_targets", forbidden)
    packet = dto.evaluate_display(prepared.copy_prefix(), evaluated, include_geometry=False)
    assert packet["candidate"] is None
    assert packet["feasibility"]["op_type"] == "twist"


def test_group_control_budget_refuses_before_geometry_or_serialization(monkeypatch):
    from backend.api import part_deformation_preview_dto as dto
    from backend.core import design_geometry
    from backend.core.part_group_model import PartGroup

    _source, prepared = _prepared()
    prefix = prepared.copy_prefix()
    evaluated = preview.evaluate(prepared, {})
    prefix.group_organization.groups[0].name = "x" * 500_001

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No geometry or control serialization before admission")

    monkeypatch.setattr(design_geometry, "_geometry_for_design", forbidden)
    monkeypatch.setattr(PartGroup, "model_dump", forbidden)
    with pytest.raises(CommandContractError) as error:
        dto.prepare_display(prefix, evaluated)
    assert error.value.code == "preview_limit"


@pytest.mark.parametrize("stage", ["prepare", "geometry", "controls_only"])
def test_selected_scope_is_exact_owned_native_result_even_without_geometry(stage):
    from backend.api import part_deformation_preview_dto as dto

    _source, prepared = _prepared()
    evaluated = preview.evaluate(prepared, {"targets": [{"kind": "part_group", "id": "other"}]})
    prefix = prepared.copy_prefix()
    packet = (dto.prepare_display(prefix, evaluated) if stage == "prepare" else
              dto.evaluate_display(prefix, evaluated, include_geometry=stage == "geometry"))
    expected = evaluated.entry.op_snapshot.model_dump(mode="json", include={
        "id", "affected_helix_ids", "target_ranges"})
    assert packet["selected_scope"] == expected
    assert packet["projection_version"] == 2
    if packet["candidate"] is not None:
        selected = packet["candidate"]["display_topology"]["deformations"][-1]
        assert packet["selected_scope"] == {key: selected[key] for key in expected}
    packet["selected_scope"]["affected_helix_ids"].clear()
    packet["selected_scope"]["target_ranges"][0]["start_bp"] = -999
    assert evaluated.entry.op_snapshot.model_dump(mode="json", include=set(expected)) == expected
