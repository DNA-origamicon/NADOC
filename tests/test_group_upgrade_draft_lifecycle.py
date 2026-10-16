"""Explicit group upgrade proposals survive ordinary draft/capture lifecycles."""

import pytest

from backend.api.part_proof_commands import dependencies
from backend.core.models import Design
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_draft_evaluation import compile_draft_evaluation
from backend.core.part_repair_draft_host import parse_draft_request, prepare_draft
from backend.core.part_repair_proposal import DraftInputError
from tests.test_group_creation_v2 import grouping, row, source
from tests.test_part_deformation_preview import _append


@pytest.fixture(autouse=True)
def semantic_capture_clock(monkeypatch):
    # These tests check draft semantics, not timing qualification. Keep the
    # production 25ms configuration and node/byte accounting, but isolate these
    # tiny semantic captures from unrelated scheduling/GC pauses. Deadline
    # refusal itself remains covered by the existing capture boundary tests.
    monkeypatch.setattr("backend.core.part_repair_capture.monotonic", lambda: 0.0)


def basis():
    original = source()
    group = grouping(original).model_copy(update={"helix_ids": [original.helices[0].id]})
    return _append(original, row(group, 1).model_copy(update={"id": "old-group"}))


def helper():
    from backend.core import part_group_repair
    return part_group_repair


def request(design, draft=None, *, operation="create", actions=None):
    body = {"draft_version": 1, "operation": operation, "expected_design_id": design.id,
            "expected_revision": 7, "expected_draft_id": draft.draft_id if draft else None,
            "expected_generation": draft.generation if draft else None}
    if actions is not None:
        body["actions"] = actions
    elif operation in {"create", "update"}:
        body["actions"] = [helper().upgrade_action(design.feature_log[-1])]
    return parse_draft_request(body)


def proposal(design, draft=None, *, operation="create", actions=None):
    body = request(design, draft, operation=operation, actions=actions)
    selected = draft.actions if operation == "rebase" and body.actions is None else body.actions
    capture = capture_draft_inputs(design, source_revision=7, draft=draft, proposed_actions=selected)
    return prepare_draft(capture, body, dependencies=dependencies, new_draft_id="group-upgrade-draft")


def test_definition_capture_discovers_upgrade_without_serializing_or_hashing(monkeypatch):
    from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform

    design = basis()
    body = request(design)
    monkeypatch.setattr(helper(), "digest", lambda *_: pytest.fail("Locked capture hashed grouping"))
    monkeypatch.setattr(ClusterCreateLogEntry, "model_dump", lambda *_a, **_k: pytest.fail("Locked capture serialized grouping"))
    monkeypatch.setattr(ClusterRigidTransform, "model_dump", lambda *_a, **_k: pytest.fail("Locked capture serialized cluster"))
    captured = capture_draft_inputs(design, source_revision=7, proposed_actions=body.actions)
    assert captured.feature_log[-1] is not design.feature_log[-1]
    assert captured.feature_log[-1].proof_version == 1
    captured.feature_log[-1].cluster_snapshot.helix_ids.clear()
    assert design.feature_log[-1].cluster_snapshot.helix_ids


def test_saved_proposal_and_design_snapshot_roundtrip_keep_exact_old_receipt():
    from backend.api.state import _snapshot_copy

    design = basis()
    before = design.model_dump_json()
    draft = proposal(design)
    expected = helper().upgrade_action(design.feature_log[-1])
    assert draft.actions[0].model_dump(mode="json") == expected
    assert RepairDraft.model_validate_json(draft.model_dump_json()) == draft
    saved = design.copy_with(repair_draft=draft)
    assert Design.model_validate_json(saved.model_dump_json()).repair_draft == draft
    assert _snapshot_copy(saved).repair_draft == draft
    assert design.model_dump_json() == before
    assert "proof_version" not in expected and "candidate" not in expected


def test_unchanged_row_rebases_after_unrelated_root_change_without_refreshing_expectations():
    design = basis()
    draft = proposal(design)
    changed = design.copy_with(recipe_root=design.recipe_root.model_copy(update={"initial_name": "Different root name"}))
    with pytest.raises(DraftInputError) as error:
        proposal(changed, draft, operation="update")
    assert error.value.code == "draft_rebase_required"
    rebased = proposal(changed, draft, operation="rebase")
    assert rebased.base != draft.base and rebased.actions == draft.actions
    assert rebased.generation == draft.generation + 1


def test_rebase_rejects_full_typed_row_digest_change_until_fresh_explicit_action():
    design = basis()
    draft = proposal(design)
    changed = design.model_copy(deep=True)
    changed.feature_log[-1].cluster_snapshot.color = "#ff0000"
    with pytest.raises(DraftInputError) as error:
        proposal(changed, draft, operation="rebase")
    assert error.value.code == "repair_conflict"
    assert error.value.as_issue()["feature_id"] == "old-group"
    fresh = helper().upgrade_action(changed.feature_log[-1])
    assert fresh["expected_definition_sha256"] != draft.actions[0].expected_definition_sha256
    rebased = proposal(changed, draft, operation="rebase", actions=[fresh])
    assert rebased.actions[0].model_dump(mode="json") == fresh
    assert draft.actions[0].expected_definition_sha256 != fresh["expected_definition_sha256"]


def test_saved_upgrade_compiles_to_ordinary_worker_request_without_replanning(monkeypatch):
    design = basis()
    draft = proposal(design)
    design = design.copy_with(repair_draft=draft)
    captured = capture_draft_inputs(design, source_revision=7, draft=draft)
    monkeypatch.setattr("backend.core.part_repair_planning.plan_actions",
                        lambda *_a, **_k: pytest.fail("Draft compiler replanned upgrade"))
    compiled = compile_draft_evaluation(captured, {"draft_version": 1,
        "expected_design_id": design.id, "expected_revision": 7,
        "expected_draft_id": draft.draft_id, "expected_generation": draft.generation})
    assert compiled.actions == draft.actions
    assert compiled.actions[0] is not draft.actions[0]
    assert compiled.expected_revision == 7


def test_group_upgrade_does_not_enable_reference_selection_for_overlay():
    from backend.api.part_repair_selection import prepare_selection

    design = basis()
    result = prepare_selection(design, {"selection_version": 1, "expected_design_id": design.id,
        "expected_revision": 7, "feature_id": "old-group", "parameter_path": ["cluster_id"],
        "expected_old": design.feature_log[-1].cluster_id}, source_revision=7,
        executor=lambda *_a, **_k: pytest.fail("Overlay reference selection replayed"),
        dependency_resolver=dependencies)
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "unsupported_reference_slot"
