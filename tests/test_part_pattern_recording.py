"""Owned ordinary pattern requests prove inputs and publish one replacement.

Most fault cases run the real evaluator through a controlled process seam. One
tiny spawned case exercises actual transport; no scientific solver is mocked as
having passed, and no saved recovery body supplies construction evidence.
"""

from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.core.models import Design
from tests.test_group_organization_history import _poison, _verified, history


def host():
    from backend.api import part_pattern_recording

    return part_pattern_recording


def transaction_host():
    from backend.api import part_ordinary_recipe_recording

    return part_ordinary_recipe_recording


@pytest.fixture
def document(monkeypatch):
    _, states = history()
    source = states[3]
    source.annotations_enabled = False
    doc = f"__owned_pattern__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    previous = (doc_context.current_request_revision(),
                doc_context.current_request_feature_log_entry_id())
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    try:
        state.load_design(source)
        yield state._sessions[doc]
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(previous[0])
        doc_context.set_request_feature_log_entry_id(previous[1])


@pytest.fixture
def worker(monkeypatch):
    from backend.api.part_evaluation import evaluate

    controls = SimpleNamespace(instances=[], on_start=None, on_result=None, transform=None)

    class Worker:
        def __init__(self, source, operation):
            self.source, self.operation = source, deepcopy(operation)
            self.closed = False
            controls.instances.append(self)

        def start(self):
            if controls.on_start is not None:
                controls.on_start(self)

        def wait(self, _timeout):
            return True

        def is_alive(self):
            return False

        def result(self):
            result = evaluate(self.source, self.operation)
            if controls.on_result is not None:
                controls.on_result(self)
            return controls.transform(result) if controls.transform is not None else result

        def close(self):
            self.closed = True

    monkeypatch.setattr(transaction_host(), "EvaluationWorker", Worker)
    return controls


def inputs(kind="linear-pattern"):
    copied = {"version": 1, "group_ids": ["placement"]}
    if kind == "circular-pattern":
        return {"cluster_id": "placement", "instances": 2, "total_angle": 90,
                "axis_point": [0, 0, 0], "axis_direction": [0, 0, 1],
                "_organization_copy": copied}
    return {"cluster_ids": ["placement"], "instances": 2, "spacing": 8,
            "direction": "X", "_organization_copy": copied}


def create(session, kind="linear-pattern", params=None, **changes):
    return host().create(kind, inputs(kind) if params is None else params,
        **{"expected_design_id": session.design.id,
           "expected_revision": session.revision, **changes})


def edit(session, params, **changes):
    index = len(session.design.feature_log) - 1
    return host().edit(index, params,
        **{"expected_feature_id": session.design.feature_log[index].id,
           "expected_design_id": session.design.id,
           "expected_revision": session.revision, **changes})


def saved(session):
    return (session.design, session.design.model_dump_json(), session.revision,
            tuple(session.history), tuple(session.redo),
            doc_context.current_request_revision(),
            doc_context.current_request_feature_log_entry_id())


def unchanged(session, before):
    after = saved(session)
    assert after[0] is before[0]
    assert after[1:3] == before[1:3]
    for old, new in zip(before[3:5], after[3:5], strict=True):
        assert len(old) == len(new) and all(a is b for a, b in zip(old, new, strict=True))
    assert after[5:] == before[5:]


def test_reference_source_is_native_reproducible_and_roundtrips_without_pattern_host(document):
    _verified(Design.model_validate_json(document.design.model_dump_json()))
    assert document.design.group_organization is not None


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_create_edit_replay_reload_and_one_undo_per_request(document, worker, kind):
    source = document.design
    before = saved(document)
    created, report, entry, copy_report = create(document, kind)
    assert created is document.design and report is not None and copy_report
    assert entry is created.feature_log[-1] and entry.op_kind == kind
    assert entry.params["_organization_copy"] == inputs(kind)["_organization_copy"]
    assert entry.params["_proof_version"] == 1 and entry.params["history_seed"]
    assert len(created.helices) == len(source.helices) + 1
    assert len(created.group_organization.groups) == len(source.group_organization.groups) + 1
    assert created.group_organization.groups[:len(source.group_organization.groups)] == source.group_organization.groups
    assert created.cluster_transforms[:len(source.cluster_transforms)] == source.cluster_transforms
    assert created.annotations_enabled is False
    assert document.revision == before[2] + 1 and len(document.history) == len(before[3]) + 1
    assert doc_context.current_request_revision() == document.revision
    assert doc_context.current_request_feature_log_entry_id() == entry.id
    assert source.model_dump_json() == before[1]
    assert worker.instances[-1].source is not source and worker.instances[-1].closed
    _verified(Design.model_validate_json(created.model_dump_json()))
    edited, _, changed, _ = edit(document, {"instances": 3})
    assert changed.id == entry.id and changed.params["history_seed"] == entry.params["history_seed"]
    assert len(edited.feature_log) == len(created.feature_log)
    assert len(edited.helices) == len(source.helices) + 2
    assert document.revision == before[2] + 2 and len(document.history) == len(before[3]) + 2
    _verified(Design.model_validate_json(edited.model_dump_json()))
    restored, _ = state.undo()
    assert restored.model_dump(mode="json") == created.model_dump(mode="json")
    restored, _ = state.undo()
    assert restored.model_dump_json() == before[1]
    redone, _ = state.redo()
    assert redone.model_dump(mode="json") == created.model_dump(mode="json")


def test_poisoned_or_evicted_recovery_is_rebuilt_from_inputs(document, worker):
    document.design = _poison(document.design)
    created, _, entry, _ = create(document)
    document.design = _poison(created)
    document.design.feature_log[-1].evicted = True
    updated, _, changed, _ = edit(document, {"spacing": 12})
    assert changed.id == entry.id and changed.params["spacing"] == 12
    assert not changed.evicted
    _verified(updated)
    for row in updated.feature_log:
        if row.feature_type == "snapshot":
            state.decode_design_snapshot(row.post_state_gz_b64)


@pytest.mark.parametrize("change", ["missing_root", "unknown_row", "unlogged_pose"])
def test_unproved_source_never_adds_a_pattern_or_consumes_redo(document, worker, change):
    if change == "missing_root":
        document.design.recipe_root = None
    elif change == "unknown_row":
        document.design.feature_log[0].params["_proof_version"] = 987
    else:
        document.design.cluster_transforms[-1].translation = [99, 0, 0]
    document.redo.append(Design())
    before = saved(document)
    with pytest.raises(HTTPException) as caught:
        create(document)
    assert caught.value.status_code == 409
    unchanged(document, before)
    assert all(item.closed for item in worker.instances)


@pytest.mark.parametrize("guard", ["design", "revision", "missing_revision", "feature"])
def test_stale_expectations_refuse_before_worker_or_default_allocation(document, worker, monkeypatch, guard):
    if guard == "feature":
        create(document)
    before = saved(document)
    count = len(worker.instances)
    monkeypatch.setattr(transaction_host(), "uuid4", lambda: pytest.fail("Stale request allocated identity"))
    with pytest.raises(HTTPException) as caught:
        if guard == "feature":
            edit(document, {"instances": 3}, expected_feature_id="other-feature")
        else:
            changes = {"design": {"expected_design_id": "other"},
                       "revision": {"expected_revision": document.revision - 1},
                       "missing_revision": {"expected_revision": None}}[guard]
            create(document, **changes)
    assert caught.value.status_code in {409, 422}
    assert len(worker.instances) == count
    unchanged(document, before)


@pytest.mark.parametrize("change", ["source", "revision", "session", "policy", "cancel"])
def test_final_owner_cas_preserves_interleaved_work(document, worker, change):
    doc = doc_context.get_current_doc()
    cancelled = Event()
    snapshots = []

    def interleave(_worker):
        with state._lock:
            if change == "source":
                document.design = document.design.copy_with(name="Other edit")
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
            snapshots.append(saved(state._sessions[doc]))

    worker.on_result = interleave
    with pytest.raises(HTTPException) as caught:
        create(document, cancelled=cancelled)
    assert caught.value.status_code == 409
    unchanged(state._sessions[doc], snapshots[0])
    assert worker.instances[-1].closed


@pytest.mark.parametrize("failure", ["failed", "unverified", "decode_change", "structure"])
def test_failed_or_invalid_worker_candidate_never_publishes(document, worker, failure):
    before = saved(document)

    def alter(result):
        if failure in {"failed", "unverified"}:
            return {"status": failure, "issues": [{"code": "controlled_refusal"}]}
        if failure == "decode_change":
            result["candidate"]["feature_log"][-1]["params"]["_generator"] = {"value": 12.0}
            # Invalid typed value would be coerced by normal Pydantic parsing.
            result["candidate"]["helices"][0]["length_bp"] = str(result["candidate"]["helices"][0]["length_bp"])
        else:
            result["candidate"]["lattice_frames"][0]["placement_cluster_id"] = "missing-owner"
        return result

    worker.transform = alter
    with pytest.raises(HTTPException):
        create(document)
    unchanged(document, before)
    assert worker.instances[-1].closed


def test_publication_failure_restores_source_stacks_and_response_markers(document, worker, monkeypatch):
    document.redo.append(Design())
    before = saved(document)
    bump = state._bump_revision

    def fail(session):
        bump(session)
        raise RuntimeError("publication fault")

    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(RuntimeError, match="publication fault"):
        create(document)
    unchanged(document, before)


def test_native_work_runs_without_state_lock_and_publication_takes_one_undo_snapshot(document, worker, monkeypatch):
    snapshots = []
    snapshot_copy = state._snapshot_copy

    def snapshot(source):
        snapshots.append(source)
        return snapshot_copy(source)

    def starting(item):
        assert not state._lock.locked()
        assert item.source is not document.design

    monkeypatch.setattr(state, "_snapshot_copy", snapshot)
    worker.on_start = starting
    source = document.design
    create(document)
    assert snapshots == [source]


@pytest.mark.parametrize("stop", ["cancelled", "deadline", "transport_limit"])
def test_bounded_stop_preserves_state_and_releases_shared_slot(document, worker, monkeypatch, stop):
    from backend.api.part_history_verification import _slot
    from backend.api.part_verification_worker import WorkerLimit

    cancelled = Event()
    if stop == "cancelled":
        cancelled.set()
    elif stop == "deadline":
        monkeypatch.setattr(transaction_host(), "TIME_BUDGET", 0)
    else:
        def fail(_worker):
            raise WorkerLimit("bounded input")
        worker.on_start = fail
    before = saved(document)
    with pytest.raises(HTTPException) as caught:
        create(document, cancelled=cancelled)
    assert caught.value.status_code == {"cancelled": 409, "deadline": 408, "transport_limit": 413}[stop]
    unchanged(document, before)
    assert all(item.closed for item in worker.instances)
    acquired = _slot.acquire(blocking=False)
    try:
        assert acquired, "Failed owned work retained the shared history slot"
    finally:
        if acquired:
            _slot.release()


def test_gate_closed_and_protected_loadout_refuse_before_capture(document, worker, monkeypatch):
    before = saved(document)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    with pytest.raises(HTTPException) as caught:
        create(document)
    assert caught.value.status_code == 409 and not worker.instances
    unchanged(document, before)
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)

    def protected(*_args):
        raise HTTPException(409, detail={"code": "protected_simulation_loadout"})

    monkeypatch.setattr(state, "_assert_active_loadout_editable", protected)
    with pytest.raises(HTTPException) as caught:
        create(document)
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    assert not worker.instances
    unchanged(document, before)


@pytest.mark.parametrize("bad", [{}, {"version": 2, "group_ids": []},
    {"version": 1, "group_ids": ["placement", "placement"]}])
def test_organization_copy_contract_is_explicit_and_closed(document, worker, bad):
    params = inputs()
    if not bad:
        params.pop("_organization_copy")
    else:
        params["_organization_copy"] = bad
    before = saved(document)
    with pytest.raises(HTTPException):
        create(document, params=params)
    unchanged(document, before)


def test_generic_job_cannot_bypass_owned_pattern_host(document, monkeypatch):
    from backend.api import part_evaluation_jobs as jobs

    before = saved(document)
    monkeypatch.setattr(state, "capture_design_for_evaluation",
        lambda *_a, **_k: pytest.fail("Generic pattern job reached capture"))
    with pytest.raises(HTTPException) as caught:
        jobs.start({"operation": "append", "kind": "linear-pattern", "params": inputs(),
                    "expected_revision": document.revision})
    assert caught.value.status_code == 422
    unchanged(document, before)


def test_real_spawned_linear_pattern_proves_and_publishes_tiny_source(document):
    before = saved(document)
    created, _, entry, _ = create(document)
    assert created is document.design and entry is created.feature_log[-1]
    assert document.revision == before[2] + 1
    assert len(document.history) == len(before[3]) + 1
    _verified(created)
