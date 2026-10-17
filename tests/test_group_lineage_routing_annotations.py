"""Routing annotations and realization retain organization through native work.

The cold recipes use real native bundle/crossover/ligation producers. The
separate pending-cycle fixture is an explicit materialized topology control:
annotations do not break that cycle; a subsequent real nick enables retry.
No alternative routing, polarity or molecular placement calculation is used.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import crud, part_proof_commands as commands
from backend.core import lattice, models as m
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_group_lineage_crossovers import placement
from tests.test_group_lineage_transforms import organize, selected_refs
from tests.test_part_deformation_preview import _append
from tests.test_part_transform_inputs import SEED
from tests.test_part_transform_preview import snapshot


KINDS = (
    "loop-skip-clear", "loop-skip-clear-all", "loop-skip-twist", "loop-skip-bend",
    "crossover-extra-bases", "crossover-extra-bases-batch", "forced-ligation-extra-bases",
    "apply-loop-skips",
)


def request(source, kind):
    if kind in {"loop-skip-clear-all", "apply-loop-skips"}:
        values = {}
    elif kind.startswith("loop-skip"):
        values = {"helix_ids": [h.id for h in source.helices],
                  "plane_a_bp": 0, "plane_b_bp": min(h.length_bp for h in source.helices)}
        if kind == "loop-skip-twist":
            values["target_twist_deg"] = 20.0
        elif kind == "loop-skip-bend":
            values.update(radius_nm=100.0, direction_deg=0.0)
    elif kind == "forced-ligation-extra-bases":
        values = {"fl_id": source.forced_ligations[0].id, "sequence": "acg"}
    else:
        values = {"crossover_id": source.crossovers[0].id, "sequence": "tn"}
        if kind.endswith("-batch"):
            values = {"entries": [values]}
    return {"_proof_version": 1, **values}


def realization_prefix(source, kind):
    if kind != "apply-loop-skips":
        return source
    # Actual native deformation, not an injected mark result or alternative
    # planner. Both fixtures already have real cross-helix strand transitions.
    op = m.DeformationOp(id="realized-twist", type="twist", plane_a_bp=0,
        plane_b_bp=min(h.length_bp for h in source.helices),
        affected_helix_ids=[h.id for h in source.helices], cluster_ids=[],
        params={"kind": "twist", "total_degrees": 50.0})
    return _append(source, m.DeformationLogEntry(id="realized-twist-row",
        deformation_id=op.id, op_snapshot=op, proof_version=1))


def recipe_prefix():
    source = snapshot(create_empty_part("Organized routing annotations", "HONEYCOMB"),
        "bundle-create", crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=42,
            history_seed=SEED, ligate_adjacent=False).model_dump(mode="json"), "bundle")
    source = snapshot(source, "crossover-place", placement(source), "crossover")
    scaffolds = [s for s in source.strands if s.strand_type == m.StrandType.SCAFFOLD]
    assert len(scaffolds) == 2
    source = snapshot(source, "forced-ligation-create", {
        "three_prime_strand_id": scaffolds[0].id,
        "five_prime_strand_id": scaffolds[1].id,
        "_fl_id": "forced-native", "is_periodic_seam": False}, "forced")
    source = snapshot(source, "loop-skip-insert", {
        "helix_id": source.helices[0].id, "bp_index": 10, "delta": 1}, "loop")
    return organize(source, append=True)


@pytest.fixture
def source():
    return recipe_prefix()


def verify(source):
    result = assess_part_history(source, execute=commands.execute, dependencies=commands.dependencies)
    assert result["status"] == "verified", result
    assert result["native_editable"] is True


@pytest.mark.parametrize("kind", KINDS)
def test_registered_annotation_matches_complete_native_result_and_keeps_input_owned(source, kind):
    source = realization_prefix(source, kind)
    params = request(source, kind)
    before, saved_params = source.model_dump(mode="json"), deepcopy(params)
    expected = commands.execute(kind, source.copy_with(group_organization=None), params)
    actual = commands.execute(kind, source, params)
    assert actual.model_dump(exclude={"group_organization"}) == expected.model_dump(
        exclude={"group_organization"})
    assert actual.group_organization == source.group_organization
    assert actual.cluster_transforms == expected.cluster_transforms
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)
    if kind in {"loop-skip-clear", "loop-skip-clear-all"}:
        assert any(h.loop_skips for h in source.helices)
        assert not any(h.loop_skips for h in actual.helices)
    elif "extra-bases" in kind:
        field = "forced_ligations" if kind.startswith("forced") else "crossovers"
        assert getattr(actual, field)[0].extra_bases == ("ACG" if kind.startswith("forced") else "TN")
    elif kind == "apply-loop-skips":
        assert any(h.loop_skips for h in actual.helices)
        assert [h.loop_skips for h in actual.helices] != [h.loop_skips for h in source.helices]
        assert actual.strands == source.strands
    actual.group_organization.groups[-1].domain_ids.clear()
    assert source.model_dump(mode="json") == before and params == saved_params


@pytest.mark.parametrize("kind", KINDS)
def test_native_annotation_recipe_reloads_and_cold_proves_through_later_topology(source, kind):
    source = realization_prefix(source, kind)
    # Keep this feature distinct from the earlier group-create named selected;
    # realization is a top-level snapshot, while minor rows have child IDs.
    source = snapshot(source, kind, request(source, kind), "annotation-result")
    source = snapshot(source, "extrude-segment", {
        "cells": [[8, 8]], "length_bp": 3, "plane": "XY", "history_seed": SEED}, "suffix")
    # All recovery bodies are intentionally unusable; input-native proof must
    # rebuild both routing children and later topology rather than trust them.
    assert source.feature_log[1].pre_state_gz_b64 == "poisoned-pre"
    verify(source)
    restored = m.Design.model_validate_json(source.model_dump_json())
    assert restored == source
    verify(restored)


def pending_source():
    source = lattice.make_bundle_design([(0, 0), (0, 1)], 21)
    selected = next(s for s in source.strands if s.domains[0].helix_id == source.helices[0].id
                    and s.domains[0].direction == m.Direction.FORWARD)
    others = [s for s in source.strands if s.id != selected.id]
    source = commands.execute("forced-ligation-create", source, {"_proof_version": 1,
        "three_prime_strand_id": others[0].id, "five_prime_strand_id": others[1].id,
        "_fl_id": "independent-forced", "is_periodic_seam": False})
    h = source.helices[0]
    source = source.copy_with(strands=[selected, *[s for s in source.strands if s.id != selected.id]],
        crossovers=[m.Crossover(id="pending-cycle", half_a=m.HalfCrossover(
            helix_id=h.id, index=20, strand=m.Direction.FORWARD), half_b=m.HalfCrossover(
            helix_id=h.id, index=0, strand=m.Direction.FORWARD))])
    source = commands.execute("loop-skip-insert", source, {"_proof_version": 1,
        "helix_id": h.id, "bp_index": 10, "delta": 1})
    return organize(source)


@pytest.mark.parametrize("kind", KINDS)
def test_real_pending_cycle_survives_annotation_then_nick_retry_updates_all_groups(kind, monkeypatch):
    source = realization_prefix(pending_source(), kind)
    before = source.model_dump(mode="json")
    actual_retry, calls = lattice.retry_pending_ligations, []

    def retry(before, after):
        calls.append((before, after))
        return actual_retry(before, after)

    monkeypatch.setattr(lattice, "retry_pending_ligations", retry)
    annotated = commands.execute(kind, source, request(source, kind))
    assert len(calls) == 1 and calls[0][0] is source
    assert annotated.strands == source.strands
    assert lattice._unligated_ids_inline(annotated) == {"pending-cycle"}
    assert selected_refs(annotated) == selected_refs(source)
    old = annotated.strands[0]
    final = commands.execute("nick", annotated, {"_proof_version": 1,
        "helix_id": source.helices[0].id, "bp_index": 8, "direction": "FORWARD"})
    assert len(calls) == 2
    assert not lattice._unligated_ids_inline(final)
    survivor = next(s for s in final.strands if any(
        d.helix_id == source.helices[0].id and d.direction == m.Direction.FORWARD
        for d in s.domains))
    assert survivor.id != old.id
    assert [(d.start_bp, d.end_bp) for d in survivor.domains] == [(9, 20), (0, 8)]
    expected = [(survivor.id, 0), (survivor.id, 1)]
    assert selected_refs(final) == selected_refs(final, "overlapping") == expected
    regrouped = commands.execute("group-update", final, {"_proof_version": 1,
        "group_id": "selected", "fields": {"domain_ids": [
            {"strand_id": survivor.id, "domain_index": 1}]}})
    assert selected_refs(regrouped) == [(survivor.id, 1)]
    assert selected_refs(regrouped, "overlapping") == expected
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fault", ["missing_group_member", "metadata_limit"])
def test_group_admission_refuses_before_native_builder_without_mutation(source, kind, fault, monkeypatch):
    from backend.api import part_ligation_commands, part_loop_commands, part_native_commands
    from backend.core import part_group_lineage

    source = realization_prefix(source, kind)
    params = request(source, kind)
    if fault == "missing_group_member":
        source.group_organization.groups[-1].domain_ids[0].strand_id = "missing"
    else:
        monkeypatch.setattr(part_group_lineage, "MAX_ITEMS", 1)
    before = source.model_dump(mode="json")
    module, function = ((part_loop_commands, "build") if kind == "apply-loop-skips" else
                        (part_native_commands, "build_loop") if kind.startswith("loop-skip")
                        else (part_ligation_commands, "build"))
    monkeypatch.setattr(module, function, lambda *_: pytest.fail("native builder ran before admission"))
    with pytest.raises(CommandContractError) as caught:
        commands.execute(kind, source, params)
    assert caught.value.code == ("missing_reference" if fault == "missing_group_member" else "group_lineage_limit")
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", [k for k in KINDS if k not in {"loop-skip-clear-all", "apply-loop-skips"}])
def test_missing_command_target_refuses_without_partial_change(source, kind):
    params = request(source, kind)
    if kind.startswith("loop-skip"):
        params["helix_ids"].append("missing")
    elif kind.endswith("-batch"):
        params["entries"].append({"crossover_id": "missing", "sequence": "A"})
    else:
        params["fl_id" if kind.startswith("forced") else "crossover_id"] = "missing"
    before = source.model_dump(mode="json")
    with pytest.raises((CommandContractError, ValueError, HTTPException)) as caught:
        commands.execute(kind, source, params)
    if isinstance(caught.value, CommandContractError):
        assert caught.value.code == "missing_reference"
    elif isinstance(caught.value, HTTPException):
        assert caught.value.status_code == 404
    else:
        assert "missing" in str(caught.value).lower()
    assert source.model_dump(mode="json") == before


def test_invalid_extra_base_batch_cannot_apply_valid_first_item(source):
    params = {"_proof_version": 1, "entries": [
        {"crossover_id": source.crossovers[0].id, "sequence": "AC"},
        {"crossover_id": "missing", "sequence": "invalid!"}]}
    before = source.model_dump(mode="json")
    with pytest.raises(HTTPException) as caught:
        commands.execute("crossover-extra-bases-batch", source, params)
    assert caught.value.status_code == 422
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", KINDS)
def test_routing_annotation_admission_keeps_generated_scope_closed(kind):
    from backend.api.part_group_organization_gate import require_native_command

    with pytest.raises(CommandContractError) as caught:
        require_native_command(kind, {"_proof_version": 1, "_generated_scope": {}})
    assert caught.value.code == "unsupported_group_organization_command"


def test_routing_owned_recipe_scope_still_requires_reviewed_evidence_and_live_switch(monkeypatch):
    from backend.api import part_group_organization_gate as gate

    checked = SimpleNamespace(evidence_class="owned_recipe_rebuild", admission=SimpleNamespace(
        scope_tag="organized_recipe_v1", operation="routing_edit"))
    with pytest.raises(HTTPException):
        gate.require_group_publication(None, None, checked)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    # This internal gate receives an already-verified opaque permit from the
    # publisher. It is not itself a permit constructor or authority validator.
    gate.require_group_publication(None, None, checked)
    checked.evidence_class = "owned_group_edit"
    with pytest.raises(HTTPException):
        gate.require_group_publication(None, None, checked)
