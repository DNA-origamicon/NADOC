"""Strict byte transport preserves native evaluation and ordinary admission."""

from copy import deepcopy
import base64
import gzip
from hashlib import sha256
import json
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
import os
import struct

import pytest

from backend.api import part_immutable_revision as revisions
from backend.api.part_evaluation import evaluate
from backend.core.models import Design
from backend.core.part_verification_capture import capture
from tests.test_part_registered_batch import gold, prepare, request, source


def native_source():
    candidate = prepare(body=request(gold()))["candidate"]
    candidate.feature_log[0].post_state_gz_b64 = "poisoned recovery never executes"
    return Design.model_validate_json(candidate.model_dump_json())


def operation(design, kind="verify"):
    body = {"operation": kind, "expected_revision": 7}
    if kind == "batch":
        body["batch"] = request(gold(nanoparticle_id="00000000-0000-0000-0000-000000000005"), expected_design_id=design.id)
    return {"request": body, "header": {"identity": "00000000-0000-0000-0000-000000000098",
        "timestamp": "2026-10-15T00:00:00Z", "source_revision": 7, "source_design_id": design.id}}


def packed(design=None, kind="verify"):
    from backend.api import part_immutable_worker as transport
    design = design or native_source()
    handle = revisions.prepare_revision(design)
    ticket = transport.reserve_input(handle)
    parts, binding = transport.encode_input(ticket, operation(design, kind))
    return transport, handle, parts, binding


def recovery_contents(value):
    """Compare every field and exact archive contents, excluding gzip mtime."""
    if isinstance(value, dict):
        return {key: (gzip.decompress(base64.b64decode(item)) if item and key in {
                    "design_snapshot_gz_b64", "post_state_gz_b64"} else recovery_contents(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [recovery_contents(item) for item in value]
    return value


@pytest.mark.parametrize("kind", ["verify", "batch"])
def test_byte_evaluation_matches_ordinary_native_capture_exactly(kind):
    transport, handle, parts, binding = packed(kind=kind)
    design = revisions.materialize_revision(handle)
    captured, op, actual_binding = transport.decode_input(b"".join(parts))
    assert actual_binding == binding
    assert captured.model_dump(mode="json") == capture(design, preserve_entry_types=True).model_dump(mode="json")
    assert "poisoned recovery" not in captured.model_dump_json()
    actual = transport.evaluate_payload(b"".join(parts))
    assert actual["binding"] == binding
    assert actual["result"] == evaluate(capture(design, preserve_entry_types=True), operation(design, kind))
    assert actual["result"]["status"] == ("verified" if kind == "verify" else "ready")
    assert op == operation(design, kind)


def test_reservation_retains_only_exact_handle_without_decode_or_projection(monkeypatch):
    from backend.api import part_immutable_worker as transport
    from backend.core import part_capture_inputs
    handle = revisions.prepare_revision(native_source())
    monkeypatch.setattr(revisions, "materialize_revision", lambda *_a: pytest.fail("Reservation decoded"))
    monkeypatch.setattr(part_capture_inputs, "visit_inputs", lambda *_a, **_kw: pytest.fail("Reservation projected"))
    ticket = transport.reserve_input(handle)
    assert ticket.source is handle and ticket.id == revisions.revision_metadata(handle).design_id
    assert not hasattr(ticket, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        ticket.source = object()
    with pytest.raises(TypeError):
        transport.ImmutableInput()


@pytest.mark.parametrize("value", [None, {}, b"{}", "saved-seal"])
def test_public_values_cannot_select_sealed_transport(value):
    from backend.api import part_immutable_worker as transport
    from fastapi import HTTPException
    with pytest.raises((HTTPException, ValueError, TypeError)):
        transport.reserve_input(value)


@pytest.mark.parametrize("damage", ["magic", "source_length", "operation_length", "source_hash", "operation_hash", "tail", "truncated"])
def test_bad_transport_is_refused_before_native_execution(monkeypatch, damage):
    transport, _handle, parts, _binding = packed()
    raw = bytearray(b"".join(parts))
    if damage == "magic": raw[0] ^= 1
    elif damage == "source_length": struct.pack_into("!I", raw, 8, 16_000_001)
    elif damage == "operation_length": struct.pack_into("!I", raw, 12, 256_001)
    elif damage == "source_hash": raw[16] ^= 1
    elif damage == "operation_hash": raw[48] ^= 1
    elif damage == "tail": raw.extend(b"x")
    else: del raw[-1]
    monkeypatch.setattr(transport, "native_evaluate", lambda *_a: pytest.fail("Invalid transport executed"))
    report = transport.evaluate_payload(bytes(raw))
    assert report["result"]["status"] == "unverified"
    assert "candidate" not in report["result"]


def test_noncanonical_document_cannot_gain_authority_with_recomputed_transport_hash():
    transport, _handle, parts, _binding = packed()
    body = json.dumps(json.loads(parts[1]), indent=1).encode()
    header = struct.pack("!8sII32s32s", transport.MAGIC, len(body), len(parts[2]), sha256(body).digest(), sha256(parts[2]).digest())
    result = transport.evaluate_payload(header + body + parts[2])["result"]
    assert result["status"] == "unverified" and "candidate" not in result


@pytest.mark.parametrize("change", ["operation", "revision", "design", "hidden"])
def test_child_refuses_wrong_operation_context_before_native_execution(monkeypatch, change):
    transport, handle, parts, _binding = packed()
    op = json.loads(parts[2])
    if change == "operation": op["request"] = {"operation": "append", "kind": "duplex-relax", "params": {}}
    elif change == "revision": op["header"]["source_revision"] = 8
    elif change == "design": op["header"]["source_design_id"] = "wrong"
    else: op["authority"] = True
    monkeypatch.setattr(transport, "native_evaluate", lambda *_a: pytest.fail("Invalid operation executed"))
    raw = json.dumps(op, sort_keys=True, separators=(",", ":")).encode()
    head = struct.pack("!8sII32s32s", transport.MAGIC, len(handle.payload), len(raw), sha256(handle.payload).digest(), sha256(raw).digest())
    assert transport.evaluate_payload(head + handle.payload + raw)["result"]["status"] == "unverified"


def test_operation_is_owned_and_oversize_refuses_before_buffer_allocation(monkeypatch):
    transport, handle, _parts, _binding = packed()
    op = operation(revisions.materialize_revision(handle))
    parts, _binding = transport.encode_input(transport.reserve_input(handle), op)
    op["request"]["expected_revision"] = 999
    assert json.loads(parts[-1])["request"]["expected_revision"] == 7
    from backend.api import part_verification_worker
    monkeypatch.setattr(part_verification_worker, "SharedMemory", lambda **_k: pytest.fail("Oversized operation allocated buffers"))
    op["padding"] = "x" * 256_001
    with pytest.raises(ValueError):
        transport.ImmutableEvaluationWorker(transport.reserve_input(handle), op)


def test_child_ordinary_capture_deadline_still_refuses(monkeypatch):
    transport, _handle, parts, _binding = packed()
    from backend.core import part_capture_inputs
    from itertools import count
    ticks = count(0, 1)
    monkeypatch.setattr(part_capture_inputs, "monotonic", lambda: next(ticks))
    result = transport.evaluate_payload(b"".join(parts))["result"]
    assert result["status"] == "unverified" and "candidate" not in result


def test_result_substitution_cannot_supply_a_ready_candidate(monkeypatch):
    transport, handle, _parts, _binding = packed()
    worker = transport.ImmutableEvaluationWorker(transport.reserve_input(handle), operation(revisions.materialize_revision(handle)))
    try:
        report = {"issues": [], "binding": {**worker.binding, "source_sha256": "0" * 64},
                  "result": {"status": "ready", "issues": [], "candidate": {}}}
        monkeypatch.setattr(worker, "_read_result", lambda: deepcopy(report))
        with pytest.raises(ValueError, match="binding"):
            worker.result()
    finally:
        worker.close()


@pytest.mark.parametrize("kind", ["verify", "batch"])
def test_real_spawned_byte_worker_reaps_and_preserves_exact_native_result(kind):
    transport, handle, parts, _binding = packed(kind=kind)
    expected = transport.evaluate_payload(b"".join(parts))["result"]
    worker = transport.ImmutableEvaluationWorker(transport.reserve_input(handle), operation(revisions.materialize_revision(handle), kind))
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(5)
        actual = worker.result()
        assert recovery_contents(actual) == recovery_contents(expected)
    finally:
        worker.close()
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)


def test_seal_is_scope_only_unlogged_geometry_still_cannot_verify():
    from backend.core.nanoparticle import create_gold_nanosphere
    design = source()
    design.nanoparticles = [create_gold_nanosphere(5., nanoparticle_id="unlogged")]
    design = Design.model_validate_json(design.model_dump_json())
    transport, _handle, parts, _binding = packed(design)
    assert transport.evaluate_payload(b"".join(parts))["result"]["status"] != "verified"


def test_output_limit_retains_original_binding_and_actionable_refusal():
    from backend.api.part_verification_worker import _result_bytes, failure
    transport, _handle, _parts, binding = packed()
    report = {"issues": [], "binding": binding, "result": {"status": "ready", "issues": [], "candidate": {"large": "x" * 2000}}}
    fallback = {"issues": [], "binding": binding, "result": failure("result_limit")}
    assert json.loads(_result_bytes(report, limit=512, limit_result=fallback)) == fallback
    assert len(_result_bytes(report, limit=512, limit_result=fallback)) <= 512


def _crash():
    os._exit(23)


def test_host_observed_crash_retains_worker_exited_without_accepting_unbound_output():
    transport, handle, _parts, _binding = packed()
    worker = transport.ImmutableEvaluationWorker(transport.reserve_input(handle), operation(revisions.materialize_revision(handle)))
    worker._process.close()
    worker._process = multiprocessing.get_context("spawn").Process(target=_crash, daemon=True)
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()["issues"] == [{"code": "worker_exited"}]
    finally:
        worker.close()


def test_uninitialized_ticket_is_not_a_private_reservation():
    from backend.api import part_immutable_worker as transport
    assert transport.is_immutable_input(object.__new__(transport.ImmutableInput)) is False


def test_real_spawned_native_dna_byte_worker_has_no_parent_serializer_warmup_dependency():
    from backend.api import part_immutable_worker as transport
    from tests.test_part_registered_batch import helix

    design = prepare(body=request(helix()))["candidate"]
    handle = revisions.prepare_revision(design)
    worker = transport.ImmutableEvaluationWorker(transport.reserve_input(handle), operation(design))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        expected = evaluate(capture(design, preserve_entry_types=True), operation(design))
        assert result == expected
        assert result["status"] == "verified" and result["checked_commands"] == 1
    finally:
        worker.close()
    assert worker._closed and worker._process_closed


def _block_owned_decode(input_name, input_size, output_name, entered):
    from backend.api import part_immutable_worker as transport
    from threading import Event

    def blocked(*_args):
        entered.set()
        Event().wait()

    transport._project = blocked
    transport._evaluate(input_name, input_size, output_name)


def test_byte_worker_cancellation_reaps_during_owned_decode_and_releases_buffers():
    from time import perf_counter

    transport, handle, parts, _binding = packed()
    worker = transport.ImmutableEvaluationWorker(transport.reserve_input(handle), operation(revisions.materialize_revision(handle)))
    names = [buffer.name for buffer in worker._buffers]
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    worker._process.close()
    worker._process = context.Process(target=_block_owned_decode,
        args=(names[0], sum(map(len, parts)), names[1], entered), daemon=True)
    try:
        worker.start()
        assert entered.wait(5), "Child did not reach its owned decode boundary"
        began = perf_counter()
        worker.close()
        assert perf_counter() - began < 2
        assert worker._closed and worker._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError):
                SharedMemory(name=name)
    finally:
        worker.close()
