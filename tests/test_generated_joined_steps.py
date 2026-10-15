"""Joined recipes preserve native geometry and ordinary overlay edit semantics."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from backend.api.generated_history import GeneratedHistory
from backend.api.generated_joined_steps import build_joined_sections, route_joined_sections
from backend.api.part_proof_commands import execute
from backend.core.joined_branches import joined_seed
from backend.core.models import LatticeType
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_overlay_commands import command_input
from backend.core.part_scope_references import remap_design
from backend.core.two_np_generator import GeneratorSettings
from tests.test_part_branch_commands import SEED, native_names
from tests.test_part_joined_path_commands import selected_plan


@pytest.mark.parametrize("lattice", list(LatticeType))
def test_compiled_joined_seed_matches_native_and_maps_only_typed_references(lattice):
    source = create_empty_part("Joined construction", lattice.value)
    summary = selected_plan(lattice, extras=13)
    expected = joined_seed(lattice, summary)
    original = deepcopy(summary)
    for spec in summary["join_sections"]:
        if "path" in spec:
            spec["path"] = {"positions": "poisoned", "frames": "poisoned"}
    history = GeneratedHistory(source, GeneratorSettings())
    actual, compiled = build_joined_sections(source, summary, history, history_seed=SEED)
    normalized = native_names(actual, expected)
    normalized = remap_design(normalized, {("cluster", actual.id): expected.id
                                          for actual, expected in zip(actual.cluster_transforms,
                                                                      expected.cluster_transforms)})
    for field in AUTHORING_FIELDS - {"metadata"}:
        assert getattr(normalized, field) == getattr(expected, field), field
    assert summary["join_sections"][1]["id"] == original["join_sections"][1]["id"]
    assert "join_section_cluster_ids" not in summary
    assert compiled["join_section_cluster_ids"] == {
        old["id"]: new["id"]
        for old, new in zip(original["join_sections"], compiled["join_sections"])
    }
    groups = [entry for entry in history.design.feature_log if entry.feature_type == "cluster_create"]
    poses = [entry for entry in history.design.feature_log if entry.feature_type == "cluster_op"]
    assert len(groups) == len(poses) == len(compiled["join_sections"])
    assert history.source_ids == {entry.cluster_id for entry in groups}
    for group in groups:
        UUID(group.cluster_id)
        assert all(identity.startswith(f"gen_{history.group_id}_") for identity in group.helix_ids)
        assert group.proof_version == 1
        assert "_generated_scope" not in command_input(group)[1]
    rebuilt = source
    for entry in history.design.feature_log:
        kind, params = command_input(entry)
        rebuilt = execute(kind, rebuilt, params)
    for field in AUTHORING_FIELDS:
        assert getattr(rebuilt, field) == getattr(history.design, field), field


def test_generated_overlay_cannot_certify_a_change_absent_from_its_inputs():
    source = create_empty_part("Joined construction", "HONEYCOMB")
    history = GeneratedHistory(source, GeneratorSettings())
    local, _ = build_joined_sections(source, selected_plan(), history, history_seed=SEED)
    cluster = local.cluster_transforms[0]
    params = {"cluster_id": cluster.id, "translation": [1, 2, 3],
              "rotation": cluster.rotation, "pivot": cluster.pivot, "_proof_version": 1}
    after = execute("cluster_op", local, params)
    after = after.copy_with(cluster_transforms=[after.cluster_transforms[0].model_copy(
        update={"name": "unrecorded change"}), *after.cluster_transforms[1:]])
    before = history.design.model_dump_json()
    with pytest.raises(ValueError, match="authored inputs"):
        history.record(local, after, "cluster_op", "Move", params, "bad-pose")
    assert history.design.model_dump_json() == before


def test_joined_routing_records_each_native_section_and_join():
    from backend.core.joined_branches import _fit_stem

    source = create_empty_part("Joined construction", "HONEYCOMB")
    history = GeneratedHistory(source, GeneratorSettings())
    summary = selected_plan()
    _fit_stem(summary, source.lattice_type)
    local, summary = build_joined_sections(source, summary, history, history_seed=uuid4())
    local, routing = route_joined_sections(local, summary, history)
    assert routing.valid and len(local.scaffolds()) == 1
    rows = history.design.feature_log
    kinds = [getattr(row, "op_kind", row.feature_type) for row in rows]
    assert kinds.count("auto-scaffold-bounded-section") == len(summary["join_sections"])
    assert kinds.count("cluster-join") == len(summary["join_crossbars"])
    assert not history.unverified_steps
    assert "generate-design" not in kinds
