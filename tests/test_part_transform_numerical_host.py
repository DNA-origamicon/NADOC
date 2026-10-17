"""Real numerical producer recipes through the owned asynchronous editor host.

No imported root, saved output, disk fixture or native scratch supplies a result.
These focused cases exercise real spawned computation and its supervisor;
they are software lifecycle checks, not molecular validity or latency claims.
"""

import json
from multiprocessing.shared_memory import SharedMemory
from threading import Event, Timer
from time import monotonic, perf_counter

import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview as prefix_service
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_transform_preview_computation as computation
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_history_verification import _slot as proof_slot
from backend.core import models as m
from backend.core.part_history_proof import command_rows
from backend.core.part_verification_capture import capture
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_transform_numerical_history import (
    STAMP, WORKER_CEILING_SECONDS, _candidate, _seed,
    native_cpd_prefix, native_duplex_prefix, poison_recovery, selected_transform,
)
from tests.test_part_transform_preview import FEATURE
from tests.test_part_transform_gesture_contract import gesture_draft
from tests import test_part_transform_preview_sessions as preview_sessions
from tests.test_part_transform_preview_sessions import opening, update


document = preview_sessions.document


def _unlinked(names):
    found = []
    for name in names:
        try:
            leaked = SharedMemory(name=name)
        except FileNotFoundError:
            continue
        leaked.close()
        leaked.unlink()
        found.append(name)
    assert not found, "Numerical history operation leaked shared-memory transport"


def _evaluation(source, request, identity):
    """Initial producers and final independent proof use the existing worker."""
    worker = EvaluationWorker(capture(source, preserve_entry_types=True), {
        "request": request, "header": {"identity": identity, "timestamp": STAMP,
                                        "source_design_id": source.id, "source_revision": 0},
    })
    names = [buffer.name for buffer in worker._buffers]
    started = perf_counter()
    try:
        worker.start()
        deadline = monotonic() + WORKER_CEILING_SECONDS
        while True:
            remaining = deadline - monotonic()
            assert remaining > 0, "Native operation exceeded the existing 180-second ceiling"
            if worker.wait(min(1.0, remaining)):
                return worker.result(), perf_counter() - started
    finally:
        worker.close()
        assert worker._closed and worker._process_closed and not worker.is_alive()
        _unlinked(names)


def _recipe(family, timings, gesture):
    if family == "cpd":
        source, ids = native_cpd_prefix()
        created, timings["cpd_create"] = _evaluation(source, {
            "operation": "append", "kind": "photoproduct-create",
            "params": {"source": {"kind": "native"}, **ids},
        }, _seed(40))
        source = poison_recovery(_candidate(created))
        params = {"source": {"kind": "native"}, "photoproduct_id": source.photoproduct_junctions[0].id}
        kind, cluster_id = "photoproduct-relax", None
    else:
        source, ids = native_duplex_prefix()
        params = {"source": {"kind": "native"}, "duplex_id": ids["duplex_id"]}
        kind, cluster_id = "duplex-relax", ids["primary"]
    relaxed, timings[kind] = _evaluation(source, {
        "operation": "append", "kind": kind, "params": params,
    }, _seed(41))
    source = _candidate(relaxed)
    if gesture in {"duplex-root", "duplex-taut"}:
        # The duplex placement owns these controls; the original fixture's
        # primary is the driven arm, which instead owns the revolute joint.
        cluster_id = next(owner.id for owner in source.cluster_transforms
                          if owner.overhang_duplex_driver_id == ids["driver"])
    source = poison_recovery(selected_transform(source, cluster_id=cluster_id))
    assert source.recipe_root.kind == "empty" and source.recipe_root.source_json is None
    assert not source.input_sources
    return source, {**ids, "joint": ids.get("joint_id")}


@pytest.fixture
def real_supervision(document, monkeypatch):
    """Observe real constructors only; preserve thread context and supervision."""
    workers, threads, timers = [], [], []
    worker_type, thread_type = computation.TransformPreviewWorker, computation.Thread

    class ObservedWorker(worker_type):
        def __init__(self, source, feature_id, *, params=None):
            assert doc_context.get_current_doc() == document
            assert source is not state.get_or_404() and source.atomistic_reference is None
            assert feature_id == FEATURE
            for parent in source.feature_log:
                for row in (parent, *getattr(parent, "children", ())):
                    for field in ("design_snapshot_gz_b64", "post_state_gz_b64", "pre_state_gz_b64",
                                  "diff_added_b64", "diff_removed_b64", "diff_modified_b64"):
                        assert not getattr(row, field, None), "Captured numerical inputs retained recovery output"
            super().__init__(source, feature_id, params=params)
            workers.append((self, [buffer.name for buffer in self._buffers]))

    def thread(*args, **kwargs):
        result = thread_type(*args, **kwargs)
        threads.append(result)
        return result

    def timer(*args, **kwargs):
        result = Timer(*args, **kwargs)
        timers.append(result)
        return result

    monkeypatch.setattr(computation, "TransformPreviewWorker", ObservedWorker)
    monkeypatch.setattr(computation, "Thread", thread)
    monkeypatch.setattr(host, "Timer", timer)
    try:
        yield {"doc": document, "workers": workers, "threads": threads}
    finally:
        # Signal cancellation before joining, including failed test bodies. A
        # reserved commit remains owned until its normal atomic finish.
        with host._lock:
            entry = host._entries.get(document)
            if entry is not None and entry.computation is not None and entry.phase != "committing":
                entry.computation.cancelled.set()
        _join(threads, monotonic() + WORKER_CEILING_SECONDS)
        host.clear_for_testing()
        for value in timers:
            value.cancel()
            if value.ident is not None:
                value.join(timeout=1)
            assert not value.is_alive()
        for worker, names in workers:
            assert worker._closed and worker._process_closed and not worker.is_alive()
            _unlinked(names)
        for slot in (host._work_slot, proof_slot):
            assert slot.acquire(blocking=False), "Numerical preview leaked work admission"
            slot.release()


def _join(threads, deadline):
    for thread in threads:
        while thread.is_alive():
            remaining = deadline - monotonic()
            assert remaining > 0, "Numerical supervisor failed to release its operation"
            thread.join(timeout=min(1.0, remaining))


def _ready(ack, operation, lane):
    assert ack["status"] == ("preparing" if operation == "prepare" else "applying")
    assert ack["computation"]["operation"] == operation
    assert ack["computation"]["request_sequence"] == ack["request_sequence"]
    assert 0 < ack["computation"]["remaining_seconds"] <= WORKER_CEILING_SECONDS
    assert "candidate" not in ack and "result" not in ack
    deadline = monotonic() + min(WORKER_CEILING_SECONDS, ack["computation"]["remaining_seconds"])
    terminal = "ready" if operation == "prepare" else "applied"
    pause = Event()
    while True:
        value = host.status(cancellation(ack), family="transform")
        assert "failure" not in value, value
        assert value["family"] == "transform" and value["command_kind"] == "cluster_op"
        assert value["doc_id"] == lane["doc"] and value["lease_id"] == ack["lease_id"]
        assert value["request_sequence"] == ack["request_sequence"]
        if value["status"] == terminal:
            _join(lane["threads"], deadline)
            return value
        assert value["status"] in {"preparing", "applying", "committing"}, value
        remaining = deadline - monotonic()
        assert remaining > 0, "Numerical preview exceeded its acknowledged computation limit"
        pause.wait(min(.05, remaining))


@pytest.mark.slow
@pytest.mark.parametrize("family,gesture", [
    pytest.param("cpd", "free", marks=pytest.mark.atomistic),
    pytest.param("duplex", "duplex-root", marks=pytest.mark.headless),
    pytest.param("duplex", "duplex-taut", marks=pytest.mark.headless),
    pytest.param("duplex", "joint", marks=pytest.mark.headless),
    pytest.param("duplex", None, marks=pytest.mark.headless, id="duplex-single-owner"),
])
def test_real_numerical_host_prepare_evaluate_apply_undo_reload_and_cold_proof(
        real_supervision, monkeypatch, family, gesture, record_property, capsys):
    from backend.api import part_transform_preview as transform
    from backend.core import cpd_design, direct_relax, part_cpd_contract, part_duplex_relax_contract

    lane, timings = real_supervision, {}
    try:
        source, ids = _recipe(family, timings, gesture)
        source.atomistic_reference = m.AtomisticReference(
            source="ignored physical display", notes="Never numerical authoring input")
        state.load_design(source)
        before = checkpoint()
        selected = next(row for row in source.feature_log if row.id == FEATURE)
        patch = {"translation": [selected.translation[0] + .5, *selected.translation[1:]]}

        def no_parent_solver(*_args, **_kwargs):
            pytest.fail("Numerical work or runtime pin validation ran in the live host")

        monkeypatch.setattr(cpd_design, "convert_extra_pair", no_parent_solver)
        monkeypatch.setattr(cpd_design, "relax_existing_cpd", no_parent_solver)
        monkeypatch.setattr(direct_relax, "relax_direct_binding", no_parent_solver)
        monkeypatch.setattr(part_cpd_contract, "runtime_fingerprint", no_parent_solver)
        monkeypatch.setattr(part_duplex_relax_contract, "runtime_fingerprint", no_parent_solver)
        started = perf_counter()
        ack = host.prepare(opening(), family="transform")
        opened = _ready(ack, "prepare", lane)["result"]
        timings["host_prepare"] = perf_counter() - started
        assert opened["before"] is not None and opened["candidate"] is not None
        assert not opened["source_equivalence_checked"] and not opened["downstream_evaluated"]
        assert len(lane["workers"]) == len(lane["threads"]) == 1
        unchanged(before)

        native = prefix_service.execute
        observed = []

        def selected_only(kind, design, params):
            assert kind == "cluster_op", "A slider evaluated a prefix or suffix command"
            observed.append(kind)
            return native(kind, design, params)

        with monkeypatch.context() as guards:
            guards.setattr(prefix_service, "execute", selected_only)
            guards.setattr(prefix_service, "_replay_prefix", no_parent_solver)
            guards.setattr(transform, "_replay_prefix", no_parent_solver)
            guards.setattr(host, "prepare_change", no_parent_solver)
            durations = []
            for sequence in (1, 2, 3):
                started = perf_counter()
                packet = host.evaluate({**update(opened, sequence=sequence, params=patch),
                                       "include_geometry": sequence != 2}, family="transform")
                durations.append(perf_counter() - started)
                assert packet["request_sequence"] == sequence
                assert packet["control_state"]["inputs"]["translation"] == patch["translation"]
                assert (packet["candidate"] is None) == (sequence == 2)
                assert not packet["source_equivalence_checked"] and not packet["downstream_evaluated"]
                unchanged(before)
            timings["host_selected_evaluations"] = durations
        assert observed == ["cluster_op"] * 3 and len(lane["workers"]) == 1
        if gesture is not None:
            # Reuse the real private renderer/tool/gizmo and explicit Upgrade control.
            # No fabricated pending pose or replacement command enters this path.
            if family == "cpd":
                assert gesture_draft(opened, "free", ids, cancel=True) == {"cancelled": True}
                unchanged(before)
            native_gesture = gesture_draft(opened, gesture, ids, joint_limit=30)
            patch = native_gesture["patch"]
            assert native_gesture["pending"] and native_gesture["draft_count"] >= 2
            assert {key: patch[key] for key in ("upgrade_to", "expected_definition_sha256")} == opened[
                "control_context"]["placement_upgrade"]
            if gesture == "joint":
                assert native_gesture["joint_world_error"] < 1e-8
            if gesture == "duplex-taut":
                evidence = native_gesture["constraint_evidence"]
                assert evidence["proposed_distance"] > evidence["contour_nm"] + 3
                assert evidence["correction"] > 1e-6
            with monkeypatch.context() as guards:
                guards.setattr(prefix_service, "_replay_prefix", no_parent_solver)
                guards.setattr(transform, "_replay_prefix", no_parent_solver)
                guards.setattr(host, "prepare_change", no_parent_solver)
                evaluated = host.evaluate(update(opened, sequence=4, params=patch), family="transform")
            assert evaluated["evaluated_command_kind"] == "placement-poses"
            assert not evaluated["source_equivalence_checked"] and not evaluated["downstream_evaluated"]
            assert len(lane["workers"]) == 1
            unchanged(before)
        started = perf_counter()
        applying = host.apply(update(opened, sequence=5, params=patch), family="transform")
        receipt = _ready(applying, "apply", lane)
        timings["host_apply"] = perf_counter() - started
        assert receipt["status"] == "applied" and receipt["revision"] == before["revision"] + 1
        assert "candidate" not in receipt and "result" not in receipt
        assert state.undo_depth() == len(before["history"]) + 1
        assert len(lane["workers"]) == len(lane["threads"]) == 2
        candidate = state.get_or_404()
        assert candidate is not source and source.model_dump(mode="json") == before["json"]
        assert candidate.atomistic_reference == source.atomistic_reference
        assert doc_context.current_request_revision() == before["request_revision"]
        assert doc_context.current_request_feature_log_entry_id() == before["request_entry"]
        old_rows, new_rows = list(command_rows(source, 64)), list(command_rows(candidate, 64))
        assert [(i, k) for i, k, _ in new_rows] == [
            (i, "placement-poses" if i == FEATURE and gesture is not None else k) for i, k, _ in old_rows]
        for (identity, _kind, old), (_new_id, _new_kind, new) in zip(old_rows, new_rows, strict=True):
            if identity == FEATURE and gesture is not None:
                assert new == {**patch["definition"], "primary_authored_fields": selected.authored_fields,
                               "legacy_source": selected.source}
            else:
                assert new == ({**old, **patch} if identity == FEATURE else old)
        assert [row.id for row in candidate.feature_log[-2:]] == [FEATURE, "numerical-history-suffix"]
        assert host._entries[lane["doc"]].prepared is None
        assert host.cancel(cancellation(opened), family="transform")["status"] == "applied"
        saved_json = candidate.model_dump(mode="json")
        state.undo()
        assert state.get_or_404().model_dump(mode="json") == before["json"]
        assert state.undo_depth() == len(before["history"])
        state.redo()
        assert state.get_or_404().model_dump(mode="json") == saved_json
        recovered = poison_recovery(state.get_or_404())
        restored = m.Design.from_json(recovered.to_json())
        assert restored.model_dump(mode="json") == recovered.model_dump(mode="json")
        proof, timings["independent_cold_proof"] = _evaluation(
            restored, {"operation": "verify"}, _seed(42))
        assert proof["status"] == "verified" and proof["native_editable"], proof
        assert proof["checked_commands"] == len(new_rows) and "physical" in proof["excluded_roles"]
    finally:
        report = json.dumps({"family": family, "gesture": gesture, "seconds": timings}, sort_keys=True)
        record_property("numerical_host_timings", report)
        with capsys.disabled():
            print(f"\nnative-transform-numerical-host {report}", flush=True)
