"""Organized residue poses preserve native geometry and final routing ancestry.

The pending-cycle control deliberately distinguishes a pose (no topology change)
from a later native nick that really enables retry and changes strand ownership.
Cold-proof cases use complete native recipes; that direct routing fixture does not.
"""

from copy import deepcopy

import pytest

from backend.api import crud, part_annotation_commands, part_proof_commands as commands
from backend.api.part_recipe_edit import prepare_change
from backend.core import lattice, models as m
from backend.core.cluster_reconcile import reconcile_cluster_membership
from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture
from tests.test_part_group_lineage import cycle_source
from tests.test_part_transform_inputs import SEED, pose
from tests.test_part_transform_preview import snapshot


ROLES = ("nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete")


def request(source, kind):
    domain = source.strands[0].domains[0]
    low = min(domain.start_bp, domain.end_bp)
    body = pose(helix_id=domain.helix_id, bp_index=low + 2,
                direction=domain.direction.value)
    if kind == "nucleotide-transform-delete":
        target = source.nucleotide_transforms[0]
        return {"_proof_version": 1, "transform_id": target.id,
                "target": list(target.target_key())}
    return {"_proof_version": 1, "history_seed": SEED,
            **({"transforms": [body, {**body, "bp_index": low + 3}]}
               if kind.endswith("-batch") else body)}


def organize(source, *, append=False):
    def operation(kind, params, identity):
        nonlocal source
        source = (snapshot(source, kind, params, identity) if append
                  else commands.execute(kind, source, {"_proof_version": 1, **params}))

    operation("group-organize", {"expected_placement_ids": [
        owner.id for owner in source.cluster_transforms]}, "organize")
    selected = source.strands[0]
    for identity in ("selected", "overlapping"):
        operation("group-create", {"group": {
            "id": identity, "name": identity, "color": "#aabbcc", "opacity": .5,
            "helix_ids": [selected.domains[0].helix_id],
            "domain_ids": [{"strand_id": selected.id, "domain_index": 0}],
        }}, identity)
    return source


def prefix(kind):
    source = snapshot(create_empty_part("Organized poses", "HONEYCOMB"), "bundle-create",
        crud.BundleRequest(cells=[[0, 0]], length_bp=21, history_seed=SEED,
                           ligate_adjacent=False).model_dump(mode="json"), "bundle")
    if kind == "nucleotide-transform-delete":
        source = snapshot(source, "nucleotide-transform", request(source, "nucleotide-transform"), "earlier-pose")
    return organize(source, append=True)


def selected_refs(source, identity="selected"):
    group = next(group for group in source.group_organization.groups if group.id == identity)
    return [(ref.strand_id, ref.domain_index) for ref in group.domain_ids]


def verify(source):
    report = assess_part_history(source, execute=commands.execute, dependencies=commands.dependencies)
    assert report["status"] == "verified", report
    assert report["native_editable"] is True


@pytest.mark.parametrize("kind", ROLES)
def test_registered_organized_pose_matches_native_geometry_and_preserves_source(kind):
    import numpy as np

    source = prefix(kind)
    params = request(source, kind)
    original, inputs = source.model_dump(mode="json"), deepcopy(params)
    expected = commands.execute(kind, source.copy_with(group_organization=None), params)
    actual = commands.execute(kind, source, params)
    assert actual.model_dump(mode="json", exclude={"group_organization"}) == expected.model_dump(
        mode="json", exclude={"group_organization"})
    assert actual.group_organization == source.group_organization
    assert actual.cluster_transforms == source.cluster_transforms
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)
    for helix in actual.helices:
        actual_arrays = deformed_nucleotide_arrays(helix, actual)
        expected_arrays = deformed_nucleotide_arrays(helix, expected)
        for field in ("positions", "base_normals", "axis_tangents"):
            np.testing.assert_array_equal(actual_arrays[field], expected_arrays[field])
    assert source.model_dump(mode="json") == original and params == inputs
    # The returned organization never retains a mutable membership alias.
    actual.group_organization.groups[-1].domain_ids.clear()
    assert source.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", ROLES)
def test_organized_pose_recipe_cold_proves_and_roundtrips_with_poisoned_recovery(kind):
    source = prefix(kind)
    source = snapshot(source, kind, request(source, kind), "selected-pose")
    source = snapshot(source, "extrude-segment", {
        "cells": [[8, 8]], "length_bp": 3, "plane": "XY", "history_seed": SEED}, "suffix")
    assert all(row.evicted and row.design_snapshot_gz_b64 == "poisoned-pre"
               for row in source.feature_log)
    verify(source)
    restored = m.Design.model_validate_json(source.model_dump_json())
    assert restored == source
    verify(restored)


@pytest.mark.parametrize("kind", ROLES)
def test_upstream_native_edit_rebuilds_organized_pose_and_group_memberships(kind):
    source = prefix(kind)
    source = snapshot(source, kind, request(source, kind), "selected-pose")
    before = source.model_dump(mode="json")
    candidate, _ = prepare_change(source, capture(source, preserve_entry_types=True),
                                 0, lambda: None, params={"length_bp": 24})
    assert candidate.helices[0].length_bp == 24
    assert candidate.nucleotide_transforms == source.nucleotide_transforms
    assert candidate.group_organization == source.group_organization
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    verify(candidate)
    assert source.model_dump(mode="json") == before


def pending_source(kind):
    source = cycle_source()
    if kind == "nucleotide-transform-delete":
        source = part_annotation_commands.build(
            "nucleotide-transform", source, request(source, "nucleotide-transform"))
    return organize(source)


def test_native_pending_control_pose_keeps_cycle_and_later_nick_really_retries():
    source = cycle_source()
    posed = commands.execute("nucleotide-transform", source, request(source, "nucleotide-transform"))
    assert posed.strands == source.strands  # A rigid residue pose does not break a routing cycle.
    raw = lattice.make_nick(posed, posed.helices[0].id, 8, m.Direction.FORWARD)
    completed = lattice.retry_pending_ligations(posed, reconcile_cluster_membership(posed, raw))
    assert len(raw.strands) == 2 and len(completed.strands) == 1
    assert completed.strands[0].id != source.strands[0].id
    assert [(d.start_bp, d.end_bp) for d in completed.strands[0].domains] == [(9, 20), (0, 8)]


@pytest.mark.parametrize("kind", ROLES)
def test_pose_then_actual_pending_retry_keeps_overlapping_regrouped_descendants(kind):
    source = pending_source(kind)
    original = source.model_dump(mode="json")
    posed = commands.execute(kind, source, request(source, kind))
    assert posed.strands == source.strands
    assert selected_refs(posed) == selected_refs(source)
    params = {"_proof_version": 1, "helix_id": source.helices[0].id,
              "bp_index": 8, "direction": "FORWARD"}
    completed = commands.execute("nick", posed, params)
    survivor = completed.strands[0]
    assert len(completed.strands) == 1 and survivor.id != source.strands[0].id
    expected = [(survivor.id, 0), (survivor.id, 1)]
    assert selected_refs(completed) == selected_refs(completed, "overlapping") == expected
    # A fresh organization membership edit consumes the post-retry domain IDs.
    regrouped = commands.execute("group-update", completed, {"_proof_version": 1,
        "group_id": "selected", "fields": {"domain_ids": [
            {"strand_id": survivor.id, "domain_index": 1}]}})
    assert selected_refs(regrouped) == [(survivor.id, 1)]
    assert selected_refs(regrouped, "overlapping") == expected
    assert regrouped.cluster_transforms == completed.cluster_transforms
    assert source.model_dump(mode="json") == original


def test_organized_pose_admits_group_references_and_budget_before_native_builder(monkeypatch):
    from backend.core import part_group_lineage

    source = prefix("nucleotide-transform")
    original = source.model_dump(mode="json")
    monkeypatch.setattr(part_annotation_commands, "build", lambda *_: pytest.fail("native builder ran"))
    monkeypatch.setattr(part_group_lineage, "MAX_ITEMS", 1)
    with pytest.raises(CommandContractError) as caught:
        commands.execute("nucleotide-transform", source, request(source, "nucleotide-transform"))
    assert caught.value.code == "group_lineage_limit"
    assert source.model_dump(mode="json") == original


def test_organized_pose_refuses_stale_group_domain_before_native_builder(monkeypatch):
    source = prefix("nucleotide-transform")
    source.group_organization.groups[-1].domain_ids[0].domain_index = 99
    original = source.model_dump(mode="json")
    monkeypatch.setattr(part_annotation_commands, "build", lambda *_: pytest.fail("native builder ran"))
    with pytest.raises(CommandContractError) as caught:
        commands.execute("nucleotide-transform", source, request(source, "nucleotide-transform"))
    assert caught.value.code == "missing_reference"
    assert source.model_dump(mode="json") == original


def test_pose_admission_does_not_open_unqualified_annotation_or_generated_roles():
    from backend.api.part_group_organization_gate import require_native_command

    for kind, params in (("flexible-segment-mark", {}), ("flexible-segment-unmark", {}),
                         ("nucleotide-transform", {"_generated_scope": {}})):
        with pytest.raises(CommandContractError):
            require_native_command(kind, params)
