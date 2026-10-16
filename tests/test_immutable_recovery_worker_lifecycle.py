"""Stage-two private recovery observation and one-shot revision ownership.

Success and process cleanup use real spawned native workers. Schema negatives
control only the reaped-process/read boundary on actual workers; they cannot
create a completion or scope seal themselves. No cache files or publication.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import asdict
import json
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
import os
import struct
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

from tests.test_immutable_recovery_worker import (
    _design, _packed, _record, _stored, admission as admission, transport as transport,
)


def _refuses_take(worker, ticket, admission):
    from fastapi import HTTPException

    with pytest.raises((ValueError, TypeError, AttributeError, HTTPException)):
        worker.take_revision(ticket, admission=admission)


def _assert_unlinked(names):
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


@contextmanager
def _worker(transport, ticket):
    worker = transport.RecoveryWorker(ticket)
    names = [buffer.name for buffer in worker._buffers]
    try:
        yield worker
    finally:
        worker.close()
        assert worker._closed and worker._process_closed
        _assert_unlinked(names)


def _complete(worker):
    worker.start()
    # This waits for a tiny child; it does not change the host recovery deadline.
    assert worker.wait(5), "Small recovery worker did not exit within the existing deadline"
    result = worker.result()
    assert result["status"] == "verified" and result["native_editable"] is True, result
    assert result["issues"] == []
    worker.close()
    return result


def _replace_target(worker, target):
    worker._process.close()
    worker._process = multiprocessing.get_context("spawn").Process(target=target,
        args=(worker._input.name, worker._input.size, worker._output.name), daemon=True)


def _crash_child(_input_name, _input_size, _output_name):
    os._exit(23)


def _oversized_child(input_name, input_size, output_name):
    from backend.api import part_immutable_recovery_worker as transport

    original = transport.evaluate_payload

    def evaluate(payload):
        report = original(payload)
        report["result"]["detail"] = "x" * transport.MAX_RESULT_BYTES
        return report

    transport.evaluate_payload = evaluate
    # Exercise the real shared-memory result encoder and its existing fallback.
    transport._evaluate(input_name, input_size, output_name)


@pytest.mark.parametrize("kind", ["empty", "gold", "dna_group"])
def test_spawned_recovery_seals_original_bytes_and_all_metadata_without_parent_decode(
        transport, admission, monkeypatch, kind):
    from backend.api import part_immutable_recovery_inputs as inputs
    from backend.api import part_immutable_revision as revisions
    from backend.core.models import Design

    record = _stored(admission, kind, annotations=False)
    expected, _captured = inputs.prepare_stored(record)
    metadata = asdict(revisions.revision_metadata(expected))
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("Revision taking decoded or re-prepared the source in the parent")

    for module, name in ((inputs, "prepare_stored"), (revisions, "prepare_revision"),
            (revisions, "_decoded_exact"), (revisions, "_canonical_payload"), (revisions, "digest"),
            (Design, "model_validate"), (Design, "model_validate_json")):
        monkeypatch.setattr(module, name, forbidden)
    ticket = transport.reserve_input(record, admission=admission.handle)
    with _worker(transport, ticket) as worker:
        report = _complete(worker)
        assert not revisions.is_prepared_revision(report)
        assert not {"candidate", "payload", "_seal", "qualification"}.intersection(report)
        candidate = worker.take_revision(ticket, admission=admission.handle)
        assert revisions.is_prepared_revision(candidate)
        assert candidate.payload is ticket.payload is record.payload
        assert asdict(revisions.revision_metadata(candidate)) == metadata
        assert metadata["design_id"] != admission.doc
        assert metadata["name"] == "Recovery \u03b1\U0001f9ec\x01 input"
        assert metadata["annotations_enabled"] is False
        if kind != "empty":
            assert b"poisoned, not executable" in candidate.payload
            assert metadata["recovery_bytes"] > 0
        _refuses_take(worker, ticket, admission.handle)
    assert calls == []
    # A scope seal alone neither publishes nor grants a recovery qualification.
    assert admission.session.design is None and admission.session.revision == 0


def test_take_requires_observed_success_and_completed_cleanup(transport, admission):
    ticket, _frame, _binding = _packed(transport, admission)
    with _worker(transport, ticket) as worker:
        _refuses_take(worker, ticket, admission.handle)
        worker.start()
        assert worker.wait(5)
        # A zero-exit process has not yet produced a host-observed result.
        _refuses_take(worker, ticket, admission.handle)
        result = worker.result()
        assert result["status"] == "verified", result
        _refuses_take(worker, ticket, admission.handle)
        worker.close()
        candidate = worker.take_revision(ticket, admission=admission.handle)
        assert candidate.payload is ticket.payload
        _refuses_take(worker, ticket, admission.handle)


def test_wrong_ticket_or_admission_does_not_consume_original_completion(transport, admission):
    from backend.api import part_publication_permit as permits

    record = _stored(admission)
    ticket = transport.reserve_input(record, admission=admission.handle)
    alternate = transport.reserve_input(record, admission=admission.handle)
    context = permits.admission_context(admission.handle)
    other_admission = permits._register(permits._admissions, permits.EvaluationAdmission(), context)
    assert permits.admission_context(other_admission) is context
    assert alternate.payload is ticket.payload and alternate.nonce != ticket.nonce
    with _worker(transport, ticket) as worker:
        _complete(worker)
        for wrong_ticket, wrong_admission in ((alternate, admission.handle),
                (copy(ticket), admission.handle), (ticket, other_admission),
                (ticket, permits.EvaluationAdmission()), (ticket, None)):
            _refuses_take(worker, wrong_ticket, wrong_admission)
        replacement = memoryview(ticket.payload).tobytes()
        assert replacement == record.payload and replacement is not record.payload
        object.__setattr__(ticket, "payload", replacement)
        try:
            _refuses_take(worker, ticket, admission.handle)
        finally:
            object.__setattr__(ticket, "payload", record.payload)
        candidate = worker.take_revision(ticket, admission=admission.handle)
        assert candidate.payload is record.payload


def test_copied_worker_completion_and_forged_observation_cannot_mint_seals(transport, admission):
    ticket, _frame, _binding = _packed(transport, admission)
    with _worker(transport, ticket) as worker:
        _complete(worker)
        observation = worker._completion
        assert observation is not None
        _refuses_take(copy(worker), ticket, admission.handle)

        class DerivedWorker(transport.RecoveryWorker):
            pass

        derived = object.__new__(DerivedWorker)
        derived.__dict__.update(worker.__dict__)
        _refuses_take(derived, ticket, admission.handle)
        forged = object.__new__(transport.RecoveryWorker)
        forged.__dict__.update(worker.__dict__)
        _refuses_take(forged, ticket, admission.handle)
        # Inserting a shallow copy back into the original slot must not make it
        # the original observed completion. Owner weakref alone is insufficient.
        for replacement in (copy(observation), {"verified": True, "metadata": observation.metadata}):
            worker._completion = replacement
            try:
                _refuses_take(worker, ticket, admission.handle)
            finally:
                worker._completion = observation
        assert worker.take_revision(ticket, admission=admission.handle).payload is ticket.payload


def test_observation_cannot_be_swapped_between_successful_workers(transport, admission):
    record = _stored(admission, "empty")
    tickets = [transport.reserve_input(record, admission=admission.handle) for _ in range(2)]
    with _worker(transport, tickets[0]) as first, _worker(transport, tickets[1]) as second:
        _complete(first)
        _complete(second)
        observations = first._completion, second._completion
        first._completion, second._completion = observations[::-1]
        try:
            _refuses_take(first, tickets[0], admission.handle)
            _refuses_take(second, tickets[1], admission.handle)
        finally:
            first._completion, second._completion = observations
        assert first.take_revision(tickets[0], admission=admission.handle).payload is record.payload
        assert second.take_revision(tickets[1], admission=admission.handle).payload is record.payload


def test_returned_proof_dictionary_is_not_the_private_seal_authority(transport, admission):
    from backend.api.part_immutable_revision import revision_metadata

    ticket, _frame, _binding = _packed(transport, admission)
    with _worker(transport, ticket) as worker:
        report = _complete(worker)
        original_fingerprint = report["authoring_fingerprint"]
        report.update(status="failed", native_editable=False, authoring_fingerprint="0" * 64)
        report["issues"].append({"code": "caller_mutation"})
        candidate = worker.take_revision(ticket, admission=admission.handle)
        assert revision_metadata(candidate).authoring_sha256 == original_fingerprint
        assert candidate.payload is ticket.payload


def test_concurrent_take_mints_exactly_one_revision(transport, admission):
    from fastapi import HTTPException
    from backend.api.part_immutable_revision import is_prepared_revision

    ticket, _frame, _binding = _packed(transport, admission)
    with _worker(transport, ticket) as worker:
        _complete(worker)
        barrier = Barrier(2)

        def take():
            barrier.wait(timeout=2)
            try:
                return worker.take_revision(ticket, admission=admission.handle)
            except (ValueError, TypeError, HTTPException) as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: take(), range(2)))
        winners = [result for result in results if is_prepared_revision(result)]
        assert len(winners) == 1, results
        assert sum(isinstance(result, (ValueError, TypeError, HTTPException)) for result in results) == 1
        assert winners[0].payload is ticket.payload


def _controlled_output(worker, report):
    """A reaped-process seam for schema negatives; normal result parsing stays."""
    worker._process.close()
    worker._process = SimpleNamespace(pid=None, exitcode=0, is_alive=lambda: False, close=lambda: None)
    encoded = json.dumps(report, separators=(",", ":"), allow_nan=False).encode()
    assert len(encoded) <= worker._result_limit
    worker._output.buf[4:4 + len(encoded)] = encoded
    struct.pack_into("!I", worker._output.buf, 0, len(encoded))


_RESULT_DAMAGE = [
    (("binding", "nonce"), "0" * 32),
    (("binding", "source_sha256"), "0" * 64),
    (("binding", "context_sha256"), "0" * 64),
    (("binding", "request_sha256"), "0" * 64),
    (("binding", "version"), True),
    (("qualification",), {"verified": True}),
    (("issues",), [{"code": "transport_error"}]),
    (("metadata",), None),
    (("metadata", "payload_bytes"), 1),
    (("metadata", "name"), "x" * 1025),
    (("metadata", "history_rows"), True),
    (("metadata", "annotations_enabled"), 1),
    (("metadata", "storage_version"), True),
    (("metadata", "preservation_version"), 2),
    (("metadata", "scope_tag"), "strict_recovery_v1"),
    (("metadata", "authoring_sha256"), "0" * 64),
    (("metadata", "recipe_sha256"), "not-a-digest"),
    (("metadata", "_seal"), {"verified": True}),
    (("result", "contract_version"), True),
    (("result", "native_editable"), 1),
    (("result", "issues"), [{"code": "unverified_feature"}]),
    (("result", "authoring_fingerprint"), "0" * 64),
    (("result", "candidate"), {"verified": True}),
]


@pytest.mark.parametrize("path,value", _RESULT_DAMAGE, ids=[".".join(path) for path, _ in _RESULT_DAMAGE])
def test_malformed_or_substituted_result_never_becomes_a_scope_seal(transport, admission, path, value):
    ticket, frame, _binding = _packed(transport, admission, _stored(admission, "empty"))
    report = transport.evaluate_payload(frame)
    assert report["result"]["status"] == "verified", report
    damaged = deepcopy(report)
    target = damaged
    for key in path[:-1]:
        target = target[key]
    assert target.get(path[-1]) != value or type(target.get(path[-1])) is not type(value)
    target[path[-1]] = value
    with _worker(transport, ticket) as worker:
        _controlled_output(worker, damaged)
        with pytest.raises((ValueError, TypeError)):
            worker.result()
        worker.close()
        _refuses_take(worker, ticket, admission.handle)


def test_checked_output_seam_preserves_real_result_and_one_shot_guards(transport, admission):
    ticket, frame, _binding = _packed(transport, admission, _stored(admission, "empty"))
    report = transport.evaluate_payload(frame)
    with _worker(transport, ticket) as worker:
        _controlled_output(worker, report)
        assert worker.result() == report["result"]
        with pytest.raises(ValueError, match="already been observed"):
            worker.result()
        worker.close()
        assert worker.take_revision(ticket, admission=admission.handle).payload is ticket.payload
        _refuses_take(worker, ticket, admission.handle)


def test_overlapping_result_readers_cannot_replace_the_observed_completion(transport, admission):
    ticket, frame, _binding = _packed(transport, admission, _stored(admission, "empty"))
    report = transport.evaluate_payload(frame)
    entered, overlap = Event(), Event()
    counter_lock = Lock()
    calls = []
    with _worker(transport, ticket) as worker:
        _controlled_output(worker, report)

        def read():
            with counter_lock:
                calls.append(True)
                first = len(calls) == 1
            if first:
                entered.set()
                # A serialized second reader cannot enter this seam. The
                # bounded wait makes the old check/read race deterministic
                # without holding a barrier that deadlocks the correct lock.
                overlap.wait(.25)
            else:
                overlap.set()
            return deepcopy(report)

        worker._read_result = read

        def observe():
            try:
                return worker.result()
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(observe)
            assert entered.wait(2)
            second = pool.submit(observe)
            results = [first.result(timeout=2), second.result(timeout=2)]
        assert len(calls) == 1, "Two readers passed the one-shot observation boundary"
        assert sum(type(value) is dict for value in results) == 1
        assert sum(isinstance(value, ValueError) for value in results) == 1
        worker.close()
        assert worker.take_revision(ticket, admission=admission.handle).payload is ticket.payload
        _refuses_take(worker, ticket, admission.handle)


@pytest.mark.parametrize("target,code", [(_crash_child, "worker_exited"), (_oversized_child, "result_limit")])
def test_crash_and_actual_result_overflow_refuse_sealing_and_release_buffers(
        transport, admission, target, code):
    ticket, _frame, _binding = _packed(transport, admission, _stored(admission, "empty"))
    with _worker(transport, ticket) as worker:
        _replace_target(worker, target)
        worker.start()
        assert worker.wait(5)
        report = worker.result()
        assert report["status"] != "verified" and report["native_editable"] is False
        assert code in {issue["code"] for issue in report["issues"]}, report
        worker.close()
        _refuses_take(worker, ticket, admission.handle)


def test_real_native_mismatch_cannot_seal_even_with_valid_storage_metadata(transport, admission):
    from backend.api.part_immutable_revision import prepare_revision

    design = _design()
    design.nanoparticles[0].diameter_nm = 999.
    record = _record(admission, prepare_revision(design).payload)
    ticket, _frame, _binding = _packed(transport, admission, record)
    with _worker(transport, ticket) as worker:
        worker.start()
        assert worker.wait(5)
        report = worker.result()
        assert report["status"] == "mismatch" and report["native_editable"] is False, report
        assert "authoring_state_mismatch" in {issue["code"] for issue in report["issues"]}
        worker.close()
        _refuses_take(worker, ticket, admission.handle)
