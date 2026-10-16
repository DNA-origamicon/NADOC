"""Owned ordinary edits share isolated proof and one guarded publication.

The controlled worker runs the real evaluator; it does not manufacture a ready
candidate or a publication permit. Pattern's existing spawned test continues to
cover the shared process boundary.
"""

from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.core.models import Design
from tests.test_group_organization_history import _poison, _verified, history
from tests.test_part_pattern_recording import saved, unchanged, worker

__all__ = ["worker"]  # Shared controlled transport fixture, now at its real host.


def host():
    from backend.api import part_ordinary_recipe_recording

    return part_ordinary_recipe_recording


@pytest.fixture(params=[False, True], ids=["legacy", "organized"])
def document(request, monkeypatch):
    _, states = history()
    source = states[3 if request.param else 2]
    source.annotations_enabled = False
    token = doc_context.set_current_doc(f"__ordinary_recipe__{uuid4()}")
    markers = (doc_context.current_request_revision(),
               doc_context.current_request_feature_log_entry_id())
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    try:
        state.load_design(source)
        yield state._sessions[doc_context.get_current_doc()]
    finally:
        state.drop_doc(doc_context.get_current_doc())
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


def edit(session, **overrides):
    return host().edit_extrusion(0, {"length_bp": 18}, **{
        "expected_feature_id": session.design.feature_log[0].id,
        "expected_design_id": session.design.id,
        "expected_revision": session.revision, **overrides})


def test_reference_source_proves_independently_of_shared_host(document):
    _verified(Design.model_validate_json(document.design.model_dump_json()))


def test_edit_rebuilds_evicted_history_once_without_mutating_source(document, worker, monkeypatch):
    document.design = _poison(document.design)
    document.design.feature_log[0].evicted = True
    source = document.design
    before = saved(document)
    snapshots = []
    snapshot = state._snapshot_copy

    def copying(design):
        snapshots.append(design)
        return snapshot(design)

    def starting(item):
        assert not state._lock.locked()
        assert item.source is not source

    monkeypatch.setattr(state, "_snapshot_copy", copying)
    worker.on_start = starting
    candidate, report, entry = edit(document)
    assert candidate is document.design and report.passed
    assert entry is candidate.feature_log[0] and entry.id == source.feature_log[0].id
    assert entry.params["length_bp"] == 18
    assert entry.params["history_seed"] == source.feature_log[0].params["history_seed"]
    assert not entry.evicted
    assert all(helix.length_bp == 18 for helix in candidate.helices)
    assert candidate.group_organization == source.group_organization
    assert candidate.cluster_transforms == source.cluster_transforms
    assert candidate.annotations_enabled is False
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert document.revision == before[2] + 1 and len(document.history) == len(before[3]) + 1
    assert snapshots == [source] and worker.instances[-1].closed
    assert source.model_dump_json() == before[1]
    assert doc_context.current_request_revision() == document.revision
    assert doc_context.current_request_feature_log_entry_id() == entry.id
    _verified(Design.model_validate_json(candidate.model_dump_json()))
    state.undo()
    assert document.design.model_dump_json() == before[1]


@pytest.mark.parametrize("guard", ["design", "revision", "feature"])
def test_stale_editor_refuses_before_capture_or_worker(document, worker, monkeypatch, guard):
    before = saved(document)
    monkeypatch.setattr(host(), "capture", lambda *_a, **_k: pytest.fail("Stale editor captured source"))
    changes = {"design": {"expected_design_id": "different"},
               "revision": {"expected_revision": document.revision - 1},
               "feature": {"expected_feature_id": "different"}}[guard]
    with pytest.raises(HTTPException) as caught:
        edit(document, **changes)
    assert caught.value.status_code == 409
    unchanged(document, before)
    assert not worker.instances


@pytest.mark.parametrize("change", ["source", "revision", "session", "policy", "cancel"])
def test_final_cas_preserves_interleaved_work(document, worker, change):
    doc = doc_context.get_current_doc()
    cancelled = Event()
    observed = []

    def interleave(_worker):
        with state._lock:
            if change == "source":
                document.design = document.design.copy_with(name="Later work")
            elif change == "revision":
                document.revision += 1
            elif change == "session":
                replacement = type(document)()
                replacement.design, replacement.revision = document.design, document.revision
                state._sessions[doc] = replacement
            elif change == "policy":
                configuration, generation = policy._configuration
                policy._configuration = (configuration, generation + 1)
            else:
                cancelled.set()
            observed.append(saved(state._sessions[doc]))

    worker.on_result = interleave
    with pytest.raises(HTTPException) as caught:
        edit(document, cancelled=cancelled)
    assert caught.value.status_code == 409
    unchanged(state._sessions[doc], observed[0])
    assert worker.instances[-1].closed


@pytest.mark.parametrize("fault", ["unlogged_pose", "missing_root", "native_refusal", "decode_change"])
def test_unproved_or_failed_candidate_never_consumes_redo(document, worker, fault):
    if fault == "unlogged_pose":
        document.design.cluster_transforms[-1].translation = [90, 0, 0]
    elif fault == "missing_root":
        document.design.recipe_root = None
    elif fault == "native_refusal":
        worker.transform = lambda _result: {"status": "failed", "issues": [{"code": "native_refusal"}]}
    else:
        def changed(result):
            result["candidate"]["helices"][0]["length_bp"] = "18"
            return result
        worker.transform = changed
    document.redo.append(Design())
    before = saved(document)
    with pytest.raises(HTTPException):
        edit(document)
    unchanged(document, before)
    assert all(instance.closed for instance in worker.instances)


def test_publication_exception_restores_exact_source_and_stacks(document, worker, monkeypatch):
    document.redo.append(Design())
    before = saved(document)
    bump = state._bump_revision

    def fail(session):
        bump(session)
        raise RuntimeError("publication fault")

    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(RuntimeError, match="publication fault"):
        edit(document)
    unchanged(document, before)


def test_rollout_gate_only_applies_to_organized_sources(document, worker, monkeypatch):
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    if document.design.group_organization is None:
        assert edit(document)[0] is document.design
    else:
        before = saved(document)
        with pytest.raises(HTTPException) as caught:
            edit(document)
        assert caught.value.detail["code"] == "group_organization_not_enabled"
        unchanged(document, before)
        assert not worker.instances


def test_nonextrusion_target_cannot_use_edit_admission(document, worker):
    before = saved(document)
    with pytest.raises(HTTPException):
        host().edit_extrusion(2, {"translation": [0, 0, 0]},
            expected_feature_id=document.design.feature_log[2].id,
            expected_design_id=document.design.id, expected_revision=document.revision)
    unchanged(document, before)
    assert not worker.instances


@pytest.mark.parametrize("field", ["source_design_id", "source_revision", "expected_feature_id", "expected_kind"])
def test_private_worker_header_binds_exact_edit_target(document, monkeypatch, field):
    from backend.api import part_evaluation

    monkeypatch.setattr(part_evaluation, "_evaluate", lambda *_a, **_k: pytest.fail("Mismatched header reached proof"))
    request = {"operation": "edit", "index": 0, "params": {"length_bp": 18},
               "expected_revision": document.revision}
    header = {"extrusion_recording_version": 1, "source_design_id": document.design.id,
              "source_revision": document.revision,
              "expected_feature_id": document.design.feature_log[0].id,
              "expected_kind": "bundle-create"}
    header[field] = document.revision + 1 if field == "source_revision" else "wrong"
    result = part_evaluation.evaluate(document.design, {"request": request, "header": header})
    # Host-context rejection follows CommandContractError's unverified status;
    # it has not evaluated an authored command or diagnosed its geometry.
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] in {"invalid_capture_context", "source_changed"}
    assert result["native_editable"] is False and "candidate" not in result
