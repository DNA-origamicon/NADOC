"""Native transform editors share the bounded lease and publication host."""

from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history
from tests.test_part_deformation_preview import _append
from tests.test_part_deformation_preview_sessions import Timer, cancellation, checkpoint, unchanged
from tests.test_part_transform_preview import FEATURE, source_recipe


KINDS = ("cluster_op", "nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete")
FAMILY = "transform"


@pytest.fixture
def document(monkeypatch):
    source = source_recipe()
    identity = f"__transform_preview__{uuid4()}"
    markers = (doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())
    monkeypatch.setattr(host, "Timer", Timer)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 37))
    token = doc_context.set_current_doc(identity)
    try:
        state.load_design(source)
        yield identity
    finally:
        try:
            host.clear_for_testing()
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(markers[0])
            doc_context.set_request_feature_log_entry_id(markers[1])


def opening(**changes):
    source, revision = state.get_design_with_revision()
    return {"preview_id": str(uuid4()), "expected_design_id": source.id,
            "expected_revision": revision, "feature_id": FEATURE, **changes}


def update(opened, *, sequence=1, params=None):
    return {key: opened[key] for key in (
        "preview_id", "lease_id", "expected_design_id", "expected_revision", "feature_id",
    )} | {"request_sequence": sequence, "params": {} if params is None else params}


def verified(source):
    report = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report


def identity(packet, kind):
    assert packet["family"] == FAMILY and packet["command_kind"] == kind
    assert packet["feature_id"] == FEATURE
    assert "deformation_id" not in packet


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("organized", [False, True], ids=["ordinary", "organized-source"])
def test_four_native_roles_apply_reload_prove_and_undo_once(document, kind, organized):
    source = source_recipe(kind)
    if organized:
        # The selected feature predates conversion; its full old definition is
        # still valid, while publication must use the organized recipe permit.
        source = _append(source, SnapshotLogEntry(id="organization", op_kind="group-organize",
            label="Organize", params={"_proof_version": 1, "expected_placement_ids": [
                item.id for item in source.cluster_transforms]}))
    state.load_design(source)
    before = checkpoint()
    opened = host.prepare(opening(), family=FAMILY)
    identity(opened, kind)
    assert opened["candidate"] is not None and opened["before"] is not None
    assert opened["downstream_evaluated"] is False and opened["source_equivalence_checked"] is False
    evaluated = host.evaluate({**update(opened), "include_geometry": False}, family=FAMILY)
    identity(evaluated, kind)
    assert evaluated["candidate"] is None and "control_state" in evaluated
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2), family=FAMILY)
    identity(receipt, kind)
    assert receipt["status"] == "applied" and receipt["revision"] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    candidate = state.get_or_404()
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    restored = Design.from_json(candidate.to_json())
    assert restored.model_dump(mode="json") == candidate.model_dump(mode="json")
    verified(restored)
    status = host.status(cancellation(opened), family=FAMILY)
    assert all(status[key] == value for key, value in receipt.items())
    assert host.cancel(cancellation(opened), family=FAMILY) == receipt
    assert host._entries[document].prepared is None
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, sequence=3), family=FAMILY)
    assert caught.value.status_code == 409
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_apply_passes_only_the_explicit_patch_after_local_validation(document, monkeypatch):
    opened = host.prepare(opening(), family=FAMILY)
    patch = {"translation": [7, 8, 9]}
    original = host.prepare_change
    seen = []

    def change(*args, **kwargs):
        seen.append(deepcopy(kwargs["params"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(host, "prepare_change", change)
    host.apply(update(opened, params=patch), family=FAMILY)
    assert seen == [patch]
    entry = next(row for row in state.get_or_404().feature_log if row.id == FEATURE)
    assert entry.translation == patch["translation"]
    assert entry.authored_fields["name"] == "Arm"


@pytest.mark.parametrize("kind", KINDS[1:])
def test_residue_feature_authored_after_conversion_uses_owned_host_and_final_lineage(document, kind):
    source = source_recipe(kind, organized=True)
    rows = source.feature_log
    selected = next(row for row in rows if row.id == FEATURE)
    assert next(i for i, row in enumerate(rows) if row.id == "organize") < rows.index(selected)
    verified(source)
    state.load_design(source)
    before = checkpoint()
    groups = source.group_organization.model_dump(mode="json")
    patch = ({} if kind.endswith("-delete") else
             {"transforms": [{**selected.params["transforms"][0], "translation": [4, 5, 6]}]}
             if kind.endswith("-batch") else {"translation": [4, 5, 6]})
    opened = host.prepare(opening(), family=FAMILY)
    identity(opened, kind)
    host.evaluate(update(opened, params=patch), family=FAMILY)
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=patch), family=FAMILY)
    identity(receipt, kind)
    candidate = state.get_or_404()
    assert candidate.group_organization.model_dump(mode="json") == groups
    if not kind.endswith("-delete"):
        assert candidate.nucleotide_transforms[0].translation == [4, 5, 6]
    assert state.undo_depth() == len(before["history"]) + 1
    verified(Design.from_json(candidate.to_json()))
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_preview_and_cancel_do_not_seek_prove_or_mutate_redo(document, monkeypatch):
    from backend.api import part_recipe_edit
    state.set_design(state.get_or_404().copy_with())
    state.undo()
    before = checkpoint()
    assert before["redo"]
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_: pytest.fail("decoded recovery"))
    monkeypatch.setattr(part_recipe_edit, "assess_part_history", lambda *_a, **_k:
                        pytest.fail("source proof during preview"))
    opened = host.prepare(opening(), family=FAMILY)
    for sequence in (1, 2):
        host.evaluate(update(opened, sequence=sequence, params={"pivot": [sequence, 0, 0]}), family=FAMILY)
    assert host.cancel(cancellation(opened), family=FAMILY)["status"] == "cancelled"
    unchanged(before)


@pytest.mark.parametrize("operation", ["evaluate", "apply", "status", "cancel"])
@pytest.mark.parametrize("other_family", ["deformation", "sweep"])
def test_other_family_cannot_reuse_the_same_transform_lease(document, operation, other_family):
    opened = host.prepare(opening(), family=FAMILY)
    before = checkpoint()
    value = update(opened) if operation in {"evaluate", "apply"} else cancellation(opened)
    with pytest.raises(HTTPException) as caught:
        getattr(host, operation)(value, family=other_family)
    assert caught.value.status_code == 409
    assert host.status(cancellation(opened), family=FAMILY)["status"] == "ready"
    unchanged(before)


def test_cancel_before_prepare_and_superseded_sequence_are_shared_guards(document):
    request = opening()
    assert host.cancel(request, family=FAMILY)["status"] == "cancelled"
    with pytest.raises(HTTPException) as caught:
        host.prepare(request, family=FAMILY)
    assert caught.value.status_code == 409
    opened = host.prepare(opening(), family=FAMILY)
    host.evaluate(update(opened, sequence=2), family=FAMILY)
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family=FAMILY)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("change", ["replacement", "session-aba", "policy"])
def test_changed_origin_refuses_before_selected_native_evaluation(document, monkeypatch, change):
    from backend.api import part_transform_preview as native
    opened = host.prepare(opening(), family=FAMILY)
    if change == "replacement":
        state.load_design(state.get_or_404().model_copy(deep=True))
    elif change == "session-aba":
        source = state.get_or_404()
        state.drop_doc(document)
        state.load_design(source)
    else:
        configuration, generation = policy._configuration
        monkeypatch.setattr(policy, "_configuration", (configuration, generation + 1))
    before = checkpoint()
    monkeypatch.setattr(native, "evaluate", lambda *_a, **_k: pytest.fail("stale native evaluation"))
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family=FAMILY)
    assert caught.value.status_code == 409
    unchanged(before)


def test_explicit_reset_target_mismatch_cannot_publish_but_valid_retry_can(document):
    state.load_design(source_recipe("nucleotide-transform-delete"))
    opened = host.prepare(opening(), family=FAMILY)
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, params={"target": ["base", "wrong", 4, "FORWARD", 0]}), family=FAMILY)
    assert caught.value.status_code == 422
    unchanged(before)
    assert host.apply(update(opened, sequence=2), family=FAMILY)["status"] == "applied"


def test_apply_independently_rejects_tampered_materialization(document):
    opened = host.prepare(opening(), family=FAMILY)
    state.get_or_404().helices[0].length_bp += 1
    before = checkpoint()
    with pytest.raises(HTTPException):
        host.apply(update(opened), family=FAMILY)
    unchanged(before)


def test_deadline_after_full_rebuild_refuses_before_undo_or_publication(document, monkeypatch):
    opened = host.prepare(opening(), family=FAMILY)
    before = checkpoint()
    original = host.prepare_change
    now = host.monotonic()
    monkeypatch.setattr(host, "monotonic", lambda: now)

    def late(*args, **kwargs):
        nonlocal now
        result = original(*args, **kwargs)
        now += host.APPLY_SECONDS + 1
        return result

    monkeypatch.setattr(host, "prepare_change", late)
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family=FAMILY)
    assert caught.value.status_code == 408
    unchanged(before)


def test_all_families_share_the_same_nonqueued_work_slot(document, monkeypatch):
    from backend.api import part_transform_preview as native
    before = checkpoint()
    assert host._work_slot.acquire(blocking=False)
    try:
        monkeypatch.setattr(native, "prepare_from_capture", lambda *_a, **_k: pytest.fail("busy native work"))
        with pytest.raises(HTTPException) as caught:
            host.prepare(opening(), family=FAMILY)
        assert caught.value.status_code == 429
    finally:
        host._work_slot.release()
    unchanged(before)


def test_organization_rollout_disabled_after_prepare_refuses_apply(document, monkeypatch):
    state.load_design(source_recipe(organized=True))
    opened = host.prepare(opening(), family=FAMILY)
    before = checkpoint()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family=FAMILY)
    assert caught.value.status_code == 409
    unchanged(before)


def test_historical_constraints_are_previewed_then_downstream_edits_rebuild_on_apply(document):
    from tests.test_part_transform_preview_constraints import constrained_source

    source = constrained_source()
    assert source.cluster_joints[0].max_angle_deg == 90
    state.load_design(source)
    before = checkpoint()
    marks = [mark.model_dump(mode="json") for mark in source.flexible_segment_marks]
    opened = host.prepare(opening(), family=FAMILY)
    assert opened["control_context"]["cluster_joints"][0]["max_angle_deg"] == 25
    assert opened["control_state"]["cluster_joints"][0]["max_angle_deg"] == 25
    assert opened["control_context"]["flexible_segment_marks"] == marks
    patch = {"translation": [2, 0, 0]}
    evaluated = host.evaluate({**update(opened, params=patch), "include_geometry": False}, family=FAMILY)
    assert evaluated["candidate"] is None
    assert evaluated["control_state"]["cluster_joints"][0]["max_angle_deg"] == 25
    assert evaluated["control_state"]["flexible_segment_marks"] == marks
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=patch), family=FAMILY)
    assert receipt["revision"] == before["revision"] + 1
    candidate = state.get_or_404()
    assert candidate.cluster_transforms[0].translation == [2, 0, 0]
    assert candidate.cluster_joints[0].max_angle_deg == 90
    assert [mark.model_dump(mode="json") for mark in candidate.flexible_segment_marks] == marks
    assert state.undo_depth() == len(before["history"]) + 1
    verified(Design.from_json(candidate.to_json()))
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
