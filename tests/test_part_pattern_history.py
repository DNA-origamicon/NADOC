"""Organized patterns retain native input history independently of recovery."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.api import crud
from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_structure_gate import require_valid_structure
from tests.test_group_organization_history import _append, _edit, _verified, history


SEED = "e339c848-3815-4ccc-a86f-506c35137fba"


def inputs(kind, design, **changes):
    value = {"_proof_version": 1, "history_seed": SEED, "instances": 3,
             "_organization_copy": {"version": 1, "group_ids": ["regrouped"]}}
    if kind == "linear-pattern":
        value.update(cluster_ids=["placement"], spacing=-8, direction="X")
    else:
        value.update(cluster_id="placement", total_angle=180,
                     axis_point=[2, 3, 1], axis_direction=[0, 0, 1])
    return {**value, **changes}


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_input_replay_pattern_count_edits_and_recovery_preserve_group_ownership(kind):
    source, _ = history()
    before = source.model_dump_json()
    params = inputs(kind, source)
    created = _append(source, m.SnapshotLogEntry(
        id="pattern-feature", op_kind=kind, label="Pattern", params=params))
    assert source.model_dump_json() == before
    assert created.group_organization.groups[:len(source.group_organization.groups)] == source.group_organization.groups
    copies = created.group_organization.groups[len(source.group_organization.groups):]
    assert len(copies) == 2
    assert len({g.id for g in created.group_organization.groups}) == len(created.group_organization.groups)
    old_strands = {s.id for s in source.strands}
    assert all(g.domain_ids and all(r.strand_id not in old_strands for r in g.domain_ids) for g in copies)
    require_valid_structure(created)
    _verified(created)

    # Editing copy count keeps the surviving producer/instance identities.
    reduced = _edit(created, len(source.feature_log), {"instances": 2})
    assert reduced.group_organization.groups[-1].id == copies[0].id
    assert copies[1].id not in {g.id for g in reduced.group_organization.groups}
    _verified(reduced)
    loaded = m.Design.model_validate_json(reduced.model_dump_json())
    _verified(loaded)
    for position, expected in [(len(source.feature_log) - 1, source), (-1, loaded)]:
        recovered = crud._seek_feature_log(loaded, position)
        for field in AUTHORING_FIELDS:
            assert getattr(recovered, field) == getattr(expected, field), field


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_copied_group_is_a_real_downstream_dependency(kind):
    source, _ = history()
    patterned = _append(source, m.SnapshotLogEntry(id="pattern-feature", op_kind=kind,
        label="Pattern", params=inputs(kind, source)))
    target = patterned.group_organization.groups[-1].id
    later = _append(patterned, m.SnapshotLogEntry(id="later-group-edit", op_kind="group-update",
        label="Name copied group", params={"_proof_version": 1, "group_id": target,
                                          "fields": {"name": "Edited copy"}}))
    _verified(later)
    original = later.model_dump_json()
    with pytest.raises(HTTPException) as caught:
        _edit(later, len(source.feature_log), {"instances": 2})
    assert "missing" in str(caught.value).lower() or "reference" in str(caught.value).lower()
    assert later.model_dump_json() == original


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_pattern_dependencies_include_declared_named_groups_and_placement(kind):
    source, _ = history()
    result = dependencies(kind, inputs(kind, source))
    assert result.known and result.barrier
    assert {(r.kind, r.identity) for r in result.reads} >= {
        ("part_group", "regrouped"), ("cluster", "placement")}


@pytest.mark.parametrize("contract", [None, {"version": 2, "group_ids": []},
    {"version": 1, "group_ids": ["regrouped", "regrouped"]},
    {"version": 1, "group_ids": [], "geometry": []}])
def test_organized_pattern_requires_closed_copy_contract_before_native_work(contract, monkeypatch):
    source, _ = history()
    params = inputs("linear-pattern", source)
    if contract is None:
        del params["_organization_copy"]
    else:
        params["_organization_copy"] = deepcopy(contract)
    monkeypatch.setattr("backend.core.pattern_copy.extract_cluster_subdesign",
                        lambda *a, **k: pytest.fail("Invalid contract reached topology extraction"))
    with pytest.raises((CommandContractError, NotImplementedError, ValueError)):
        execute("linear-pattern", source, params)


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_pattern_postprocessing_tracks_original_and_copied_domain_merges(kind):
    from backend.api.pattern_features import build_pattern
    from backend.api.part_ligation_commands import ligate
    from backend.core.part_group_lineage import prepare_lineage, apply_lineage
    from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
    from tests.test_part_group_lineage import cycle_source, native_nick

    source = native_nick(cycle_source())
    source = source.copy_with(cluster_transforms=[m.ClusterRigidTransform(
        id="placement", helix_ids=[source.helices[0].id])],
        group_organization=GroupOrganization(groups=[PartGroup(id="regrouped",
            domain_ids=[GroupDomainRef(strand_id=source.strands[0].id, domain_index=0)])]))
    params = inputs(kind, source, instances=2)
    raw, _, _ = build_pattern(kind, source, params, id_seed=SEED)
    plan = prepare_lineage(raw, kind, params)
    final = raw
    # New pattern crossovers deliberately do not enter pending-ligation retry.
    # Exercise the postprocessing boundary with actual native domain merges,
    # proving it can retain both original and producer-declared copied groups.
    for helix in raw.helices:
        final = ligate(final, crud.NickRequest(helix_id=helix.id, bp_index=8,
                                             direction=m.Direction.FORWARD))
    final = apply_lineage(plan, final)
    assert len(raw.strands) == 4 and len(final.strands) == 2
    assert len(final.group_organization.groups) == 2
    final_strands = {strand.id: strand for strand in final.strands}
    for group in final.group_organization.groups:
        assert group.domain_ids
        assert all(ref.strand_id in final_strands for ref in group.domain_ids)
        assert all((final_strands[ref.strand_id].domains[ref.domain_index].start_bp,
                    final_strands[ref.strand_id].domains[ref.domain_index].end_bp)
                   == (0, 20) for ref in group.domain_ids)
    require_valid_structure(final)
