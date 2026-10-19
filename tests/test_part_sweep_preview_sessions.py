"""Sweep editor leases regenerate native inputs, independently of recovery.

Tiny ordinary native fixtures exercise the shared lease boundary. Existing
rootless sweep_history rebasing remains a separate compatibility contract.
"""

from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.sweep import SweepRequest
from tests.test_part_deformation_preview import _append
from tests.test_part_deformation_preview_sessions import (
    Timer, cancellation, checkpoint, unchanged,
)


SWEEP_ID = "bbf3fdbe-92a7-476e-8d77-4578091ed5df"
FEATURE_ID = "selected-sweep"


def recipe(*, organized=False, downstream=False, length=10):
    source = create_empty_part("Owned Sweep preview", "HONEYCOMB")
    params = SweepRequest(sweep_id=SWEEP_ID, cells=[(0, 0), (0, 1)],
        points_nm=[(0, 0, 0), (0, 0, length)], ligate_adjacent=False).model_dump(mode="json")
    source = _append(source, m.SnapshotLogEntry(id=FEATURE_ID, op_kind="sweep",
        label="Sweep", params={**params, "_proof_version": 1}))
    if organized:
        source = _append(source, m.SnapshotLogEntry(id="organization", op_kind="group-organize",
            label="Organize", params={"_proof_version": 1, "expected_placement_ids": [
                item.id for item in source.cluster_transforms]}))
    if downstream:
        target = source.helices[1].id
        params = {"_proof_version": 1, "helix_id": target,
                  "bp_index": 10, "direction": "FORWARD"}
        child = m.MinorMutationLogEntry(id="later-nick", label="Nick on second Sweep cell",
            op_subtype="nick", params=params)
        row = m.RoutingClusterLogEntry(id="later-routing", children=[child],
            pre_state_gz_b64="poisoned-routing-before", post_state_gz_b64="poisoned-routing-after",
            evicted=True)
        source = execute("nick", source, params).copy_with(feature_log=[*source.feature_log, row])
    for entry in source.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = "poisoned-before"
            entry.post_state_gz_b64 = "poisoned-after"
            entry.evicted = True
    return source


@pytest.fixture
def document(monkeypatch):
    # Fallible native fixture construction precedes document context mutation.
    source = recipe()
    identity = f"__sweep_preview__{uuid4()}"
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
            "expected_revision": revision, "feature_id": FEATURE_ID, **changes}


def update(opened, *, sequence=1, params=None):
    return {key: opened[key] for key in (
        "preview_id", "lease_id", "expected_design_id", "expected_revision", "feature_id",
    )} | {"request_sequence": sequence,
          "params": {"points_nm": [[0, 0, 0], [0, 0, 12]]} if params is None else params}


def verified(source):
    report = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report


def test_sweep_fixture_has_native_proof_despite_evicted_poisoned_recovery():
    verified(recipe(organized=True, downstream=True))


def test_prepare_evaluate_cancel_never_reads_recovery_or_changes_document(document, monkeypatch):
    state.set_design(state.get_or_404().copy_with())
    state.undo()
    before = checkpoint()
    assert before["redo"]
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_a, **_k:
        pytest.fail("Input preview decoded recovery"))
    opened = host.prepare(opening(), family="sweep")
    assert opened["deformation_id"] == "sweep_" + SWEEP_ID
    assert opened["source_equivalence_checked"] is False
    assert opened["downstream_evaluated"] is False
    for sequence in (1, 2):
        result = host.evaluate(update(opened, sequence=sequence), family="sweep")
        assert result["request_sequence"] == sequence
    assert host.cancel(cancellation(opened), family="sweep")["status"] == "cancelled"
    unchanged(before)
    with pytest.raises(HTTPException):
        host.apply(update(opened, sequence=3), family="sweep")


@pytest.mark.parametrize("organized", [False, True], ids=["ordinary", "organized"])
def test_apply_rebuilds_fixed_downstream_inputs_once_and_cold_replays(document, monkeypatch, organized):
    state.load_design(recipe(organized=organized, downstream=True))
    before = checkpoint()
    original_rows = [row.id for row in before["source"].feature_log]
    original_nick = before["source"].feature_log[-1].children[0].model_dump(mode="json")
    opened = host.prepare(opening(), family="sweep")
    # Both feature-stage preview and full Apply must derive inputs, not recovery.
    with monkeypatch.context() as scope:
        scope.setattr(state, "decode_design_snapshot", lambda *_a, **_k:
            pytest.fail("Native Apply decoded recovery"))
        host.evaluate(update(opened), family="sweep")
        receipt = host.apply(update(opened, sequence=2), family="sweep")
    current = state.get_or_404()
    assert receipt["status"] == "applied"
    assert receipt["revision"] == before["revision"] + 1
    assert receipt["deformation_id"] == "sweep_" + SWEEP_ID
    assert state.undo_depth() == len(before["history"]) + 1
    assert [row.id for row in current.feature_log] == original_rows
    assert current.feature_log[0].params["sweep_id"] == SWEEP_ID
    assert current.feature_log[-1].children[0].params == original_nick["params"]
    # Native fixed-address replay deliberately differs from legacy proportional
    # sweep_history routing rebase. No hidden sweep-follow owner is introduced.
    assert current.feature_log[-1].children[0].params["bp_index"] == 10
    assert not any(item.id.startswith("sweep-follow:") for item in current.cluster_transforms)
    expected = recipe(organized=organized, downstream=True, length=12)
    assert _geometry_for_design(current) == _geometry_for_design(expected)
    assert _geometry_for_design(current) != _geometry_for_design(before["source"])
    assert before["source"].model_dump(mode="json") == before["json"]
    verified(m.Design.model_validate_json(current.model_dump_json()))
    assert host.status(cancellation(opened), family="sweep")["revision"] == receipt["revision"]
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    state.redo()
    verified(state.get_or_404())


def test_removed_sweep_cell_removes_the_later_nick_on_its_helix(document):
    """cadnano-style: a sweep edit that removes the helix a later nick acts on
    removes that nick instead of refusing the edit."""
    state.load_design(recipe(downstream=True))
    before = checkpoint()
    nick_helix = before["source"].feature_log[-1].children[0].params["helix_id"]
    opened = host.prepare(opening(), family="sweep")
    receipt = host.apply(update(opened, params={"cells": [[0, 0]]}), family="sweep")
    assert receipt["status"] == "applied"
    published = state.get_or_404()
    assert all(c.id != "later-nick" for e in published.feature_log
               if e.feature_type == "routing-cluster" for c in e.children)
    assert all(h.id != nick_helix for h in published.helices)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_full_source_mismatch_cannot_be_promoted_by_feature_stage_preview(document):
    source = state.get_or_404().model_copy(deep=True)
    source.strands[0].color = "#123456"
    state.load_design(source)
    opened = host.prepare(opening(), family="sweep")
    before = checkpoint()
    with pytest.raises(HTTPException):
        host.apply(update(opened), family="sweep")
    unchanged(before)


@pytest.mark.parametrize("operation", ["evaluate", "apply", "status", "cancel"])
def test_deformation_family_cannot_read_publish_or_cancel_sweep_lease(document, operation):
    opened = host.prepare(opening(), family="sweep")
    before = checkpoint()
    value = update(opened) if operation in {"evaluate", "apply"} else cancellation(opened)
    with pytest.raises(HTTPException) as caught:
        getattr(host, operation)(value, family="deformation")
    assert caught.value.status_code == 409
    unchanged(before)
    assert host.status(cancellation(opened), family="sweep")["status"] == "ready"


def test_deformation_tombstone_does_not_cancel_same_nonce_sweep_opening(document):
    request = opening()
    host.cancel(cancellation(request), family="deformation")
    opened = host.prepare(request, family="sweep")
    assert opened["preview_id"] == request["preview_id"]
    assert host.cancel(cancellation(opened), family="sweep")["status"] == "cancelled"
    with pytest.raises(HTTPException):
        host.prepare(request, family="sweep")


@pytest.mark.parametrize("change", ["revision", "session_aba"])
def test_stale_revision_or_same_id_reopened_session_refuses_apply(document, change):
    opened = host.prepare(opening(), family="sweep")
    source, revision = state.get_design_with_revision()
    if change == "revision":
        state.set_design(source.copy_with())
    else:
        state.drop_doc(document)
        with state._lock:
            session = state._session()
            session.design, session.revision = source, revision
    before = checkpoint()
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family="sweep")
    assert caught.value.status_code == 409
    unchanged(before)


def test_sweep_uses_existing_nonqueued_computation_slot(document):
    opened = host.prepare(opening(), family="sweep")
    before = checkpoint()
    assert host._work_slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as caught:
            host.evaluate(update(opened), family="sweep")
        assert caught.value.status_code == 429
    finally:
        host._work_slot.release()
    unchanged(before)
    assert host.evaluate(update(opened, sequence=2), family="sweep")["request_sequence"] == 2


def test_apply_deadline_after_presentation_preservation_refuses_atomically(document, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(host, "monotonic", lambda: clock[0])
    opened = host.prepare(opening(), family="sweep")
    before = checkpoint()
    original = host.preserve_document_state

    def slow_preservation(*args, **kwargs):
        candidate = original(*args, **kwargs)
        clock[0] = host.APPLY_SECONDS + 0.01
        return candidate

    monkeypatch.setattr(host, "preserve_document_state", slow_preservation)
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened), family="sweep")
    assert caught.value.status_code == 408
    unchanged(before)
