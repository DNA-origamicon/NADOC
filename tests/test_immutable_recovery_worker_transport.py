"""Recovery transport releases its input before document preparation.

These tests run the actual child entry point in-process with bounded shared
buffers. Preparation/proof are tripwires; no process, model build, file or
publication authority is created. The protocol fixture is deliberately opaque
document bytes because document validation belongs to the patched preparation.
"""

from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import importlib
import json
from multiprocessing.shared_memory import SharedMemory
import struct
from types import SimpleNamespace

import pytest


HEADER = struct.Struct("!8sII32s32s")
SOURCE = b'{"name":"Recovery \\u03b1","retained":"\\u0000 exact bytes"}'
CONTEXT = {
    "version": 1, "doc_id": "__recovery_transport__",
    "session_identity": "original-session", "source_revision": 17,
    "policy_generation": 3, "request_sha256": "a" * 64,
    "nonce": "b" * 32, "storage_version": 1,
}


def _wire(source=SOURCE, *, raw_context=None):
    raw_context = raw_context if raw_context is not None else json.dumps(
        CONTEXT, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    header = HEADER.pack(b"NADOC-R1", len(source), len(raw_context),
                         sha256(source).digest(), sha256(raw_context).digest())
    return header + source + raw_context


def _binding(source=SOURCE):
    raw = json.dumps(CONTEXT, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"version": 1, "source_sha256": sha256(source).hexdigest(),
            "context_sha256": sha256(raw).hexdigest(),
            "request_sha256": CONTEXT["request_sha256"], "nonce": CONTEXT["nonce"]}


class _InputBuffer:
    """A real buffer exporter which forbids a whole-frame slicing shortcut.

    Python 3.12's buffer protocol still permits memoryview/struct consumers.
    Header/source/context views are supported; the old full-frame slice is
    observed without measuring RSS, tracing allocations or changing GC.
    """

    def __init__(self, view):
        self.view = view
        self.whole_frame_reads = []

    def __len__(self):
        return len(self.view)

    def __buffer__(self, _flags):
        return memoryview(self.view)

    def __release_buffer__(self, view):
        view.release()

    def __getitem__(self, key):
        if isinstance(key, slice) and key.indices(len(self.view)) == (0, len(self.view), 1):
            self.whole_frame_reads.append("slice")
            raise AssertionError("Recovery copied the complete shared frame")
        return self.view[key]

    def __bytes__(self):
        self.whole_frame_reads.append("bytes")
        raise AssertionError("Recovery copied the complete shared frame")


class _ObservedMapping:
    def __init__(self, mapping, *, guarded=False):
        self.mapping = mapping
        self.closed = False
        self.guard = _InputBuffer(mapping.buf) if guarded else None

    @property
    def buf(self):
        return self.guard if self.guard is not None else self.mapping.buf

    @property
    def size(self):
        return self.mapping.size

    def close(self):
        # Mark only a successful close: leaked exported views must fail the
        # test instead of pretending that the OS mapping was released.
        self.mapping.close()
        self.closed = True


@pytest.fixture
def transport(monkeypatch):
    module = importlib.import_module("backend.api.part_immutable_recovery_worker")
    # The child normally owns these process-local settings. Restore the parent
    # test process environment after this deliberately in-process invocation.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        monkeypatch.setenv(name, "1")
    return module


@contextmanager
def _buffers(transport, monkeypatch, payload, *, padding=0, guarded=False):
    source = SharedMemory(create=True, size=len(payload) + padding)
    output = None
    children = {"input": [], "output": []}
    try:
        output = SharedMemory(create=True, size=transport.RESULT_HEADER_BYTES + transport.MAX_RESULT_BYTES)
        source.buf[:len(payload)] = payload
        if padding:
            source.buf[len(payload):] = b"!" * (source.size - len(payload))

        def attach(*, name):
            role = "input" if name == source.name else "output" if name == output.name else None
            assert role is not None, "Worker opened an unowned shared buffer"
            child = _ObservedMapping(SharedMemory(name=name), guarded=guarded and role == "input")
            children[role].append(child)
            return child

        with monkeypatch.context() as local:
            local.setattr(transport, "SharedMemory", attach)
            yield SimpleNamespace(source=source, output=output, children=children, size=len(payload))
    finally:
        # Parent ownership is separate from the observed child's mapping. The
        # parent can still mutate its source even after the child closes it.
        try:
            for group in children.values():
                for child in group:
                    if not child.closed:
                        child.close()
        finally:
            source.close()
            source.unlink()
            if output is not None:
                output.close()
                output.unlink()


def _read_report(transport, buffers):
    size = struct.unpack_from("!I", buffers.output.buf, 0)[0]
    assert 0 < size <= transport.MAX_RESULT_BYTES
    raw = bytes(buffers.output.buf[transport.RESULT_HEADER_BYTES:transport.RESULT_HEADER_BYTES + size])
    return json.loads(raw)


def _run(transport, buffers, *, declared_size=None):
    transport._evaluate(buffers.source.name,
                        buffers.size if declared_size is None else declared_size,
                        buffers.output.name)
    assert len(buffers.children["output"]) == 1
    assert all(child.closed for group in buffers.children.values() for child in group)
    return _read_report(transport, buffers)


def _fake_preparation(monkeypatch, *, source=SOURCE, on_prepare=None, on_proof=None):
    from backend.api import part_immutable_recovery_inputs as inputs
    from backend.api import part_immutable_revision as revisions
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core import part_history_contract

    candidate = object()
    captured = {"native_inputs": ["\u03b1", 12.0, True, None], "rows": ["explicit recipe"]}
    metadata = revisions.RevisionMetadata(
        design_id="design-content-id", name="Recovered \u03b1", lattice_type="HONEYCOMB",
        payload_bytes=len(source), authoring_sha256="c" * 64, recipe_sha256="d" * 64,
        history_rows=1, recovery_bytes=0, annotations_enabled=False,
        preservation_version=1, preserved_document_sha256="e" * 64)
    result = {"status": "verified", "native_editable": True, "issues": [],
              "checked_commands": 1, "authoring_fingerprint": metadata.authoring_sha256}
    seen = SimpleNamespace(stored=[], proofs=[], candidate=candidate, captured=captured,
                           metadata=asdict(metadata), result=result)

    def prepare(stored):
        seen.stored.append(stored)
        assert type(stored.payload) is bytes and stored.payload == source
        assert asdict(stored.manifest) == {
            "doc_id": CONTEXT["doc_id"], "payload_bytes": len(source),
            "payload_sha256": sha256(source).hexdigest(), "storage_version": 1}
        assert stored.lease is None
        if on_prepare is not None:
            on_prepare(stored)
        return candidate, captured

    def revision_metadata(value):
        assert value is candidate
        return metadata

    def assess(value, **kwargs):
        seen.proofs.append(value)
        assert value == captured and value is not captured
        assert kwargs == {"execute": execute, "dependencies": dependencies}
        if on_proof is not None:
            on_proof(value)
        return result

    monkeypatch.setattr(inputs, "prepare_stored", prepare)
    monkeypatch.setattr(revisions, "revision_metadata", revision_metadata)
    monkeypatch.setattr(part_history_contract, "assess_part_history", assess)
    return seen


def test_child_closes_input_before_preparation_and_preserves_exact_report(transport, monkeypatch):
    closed_at_prepare = []
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        def prepare(_stored):
            closed_at_prepare.append([child.closed for child in buffers.children["input"]])
            assert buffers.children["output"][0].closed is False

        seen = _fake_preparation(monkeypatch, on_prepare=prepare)
        report = _run(transport, buffers)
        assert closed_at_prepare == [[True]], "Input mapping overlaps document preparation"
        assert len(seen.stored) == len(seen.proofs) == 1
        assert report == {"issues": [], "binding": _binding(),
                          "metadata": seen.metadata, "result": seen.result}


def test_owned_source_survives_parent_shared_memory_change_during_preparation(transport, monkeypatch):
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        def prepare(stored):
            buffers.source.buf[HEADER.size:HEADER.size + len(SOURCE)] = b"x" * len(SOURCE)
            assert type(stored.payload) is bytes and stored.payload == SOURCE

        seen = _fake_preparation(monkeypatch, on_prepare=prepare)
        report = _run(transport, buffers)
        assert report["result"] == seen.result
        assert report["binding"] == _binding()
        assert seen.stored[0].payload == SOURCE
        assert bytes(buffers.source.buf[HEADER.size:HEADER.size + len(SOURCE)]) != SOURCE


def test_shared_parser_uses_bounded_views_without_whole_frame_slice(transport, monkeypatch):
    source = b'{"retained":"' + b"x" * 65_536 + b'"}'
    with _buffers(transport, monkeypatch, _wire(source), guarded=True) as buffers:
        seen = _fake_preparation(monkeypatch, source=source)
        report = _run(transport, buffers)
        assert buffers.children["input"][0].guard.whole_frame_reads == []
        assert report == {"issues": [], "binding": _binding(source),
                          "metadata": seen.metadata, "result": seen.result}


def test_evaluate_payload_keeps_its_existing_exact_bytes_contract(transport, monkeypatch):
    seen = _fake_preparation(monkeypatch)
    expected = {"issues": [], "binding": _binding(), "metadata": seen.metadata, "result": seen.result}
    assert transport.evaluate_payload(_wire()) == expected
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        assert _run(transport, buffers) == expected
    assert len(seen.stored) == len(seen.proofs) == 2
    for invalid in (bytearray(_wire()), memoryview(_wire())):
        refused = transport.evaluate_payload(invalid)
        assert refused["result"]["status"] == "unverified"
    assert len(seen.stored) == 2


def _damaged_frame(damage):
    payload = bytearray(_wire())
    if damage == "magic":
        payload[0] ^= 1
    elif damage in {"source_length", "context_length"}:
        offset = 8 if damage == "source_length" else 12
        struct.pack_into("!I", payload, offset, struct.unpack_from("!I", payload, offset)[0] + 1)
    elif damage == "source_hash":
        payload[HEADER.size] ^= 1
    elif damage == "context_hash":
        payload[-1] ^= 1
    elif damage == "truncated":
        del payload[-1]
    elif damage == "tail":
        payload.extend(b"x")
    elif damage == "noncanonical":
        return _wire(raw_context=json.dumps(CONTEXT, sort_keys=True, indent=1).encode())
    elif damage == "duplicate_context":
        raw = json.dumps(CONTEXT, sort_keys=True, separators=(",", ":")).encode()
        return _wire(raw_context=raw[:-1] + b',"version":1}')
    elif damage == "context_version":
        return _wire(raw_context=json.dumps({**CONTEXT, "version": True},
            sort_keys=True, separators=(",", ":")).encode())
    return bytes(payload)


@pytest.mark.parametrize("damage", ["magic", "source_length", "context_length", "source_hash",
    "context_hash", "truncated", "tail", "noncanonical", "duplicate_context", "context_version"])
def test_invalid_shared_frame_closes_both_mappings_before_any_preparation(transport, monkeypatch, damage):
    seen = _fake_preparation(monkeypatch)
    with _buffers(transport, monkeypatch, _damaged_frame(damage)) as buffers:
        report = _run(transport, buffers)
        assert report["binding"] is None and report["metadata"] is None
        assert report["result"]["status"] == "unverified"
        assert report["result"]["issues"][0]["code"] == "strict_recovery_error"
        assert len(buffers.children["input"]) == 1
    assert seen.stored == seen.proofs == []


def test_allocation_padding_outside_declared_frame_is_not_parsed(transport, monkeypatch):
    seen = _fake_preparation(monkeypatch)
    with _buffers(transport, monkeypatch, _wire(), padding=32) as buffers:
        report = _run(transport, buffers)
        assert report == {"issues": [], "binding": _binding(),
                          "metadata": seen.metadata, "result": seen.result}


def test_declared_frame_cannot_exceed_actual_input_mapping(transport, monkeypatch):
    seen = _fake_preparation(monkeypatch)
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        report = _run(transport, buffers, declared_size=buffers.source.size + 1)
        assert report["result"]["status"] == "unverified"
        assert report["binding"] is None and report["metadata"] is None
    assert seen.stored == seen.proofs == []


def test_declared_frame_size_requires_exact_integer_before_input_mapping(transport, monkeypatch):
    seen = _fake_preparation(monkeypatch)
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        report = _run(transport, buffers, declared_size=float(buffers.size))
        assert buffers.children["input"] == []
        assert report["binding"] is None and report["metadata"] is None
        assert report["result"]["status"] == "unverified"
        assert report["result"]["issues"][0]["code"] == "strict_recovery_error"
    assert seen.stored == seen.proofs == []


def test_input_close_failure_refuses_before_preparation_and_parent_cleanup_can_retry(
        transport, monkeypatch):
    seen = _fake_preparation(monkeypatch)
    attempts = []
    original_close = _ObservedMapping.close
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        def fail_input_close_once(child):
            if child.mapping.name == buffers.source.name:
                attempts.append(child.closed)
                if len(attempts) == 1:
                    # Fail before closing the real mapping. The child must not
                    # claim successful release or start preparation afterward.
                    raise BufferError("fixture input close failure")
            original_close(child)

        monkeypatch.setattr(_ObservedMapping, "close", fail_input_close_once)
        transport._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        report = _read_report(transport, buffers)
        assert len(buffers.children["input"]) == len(buffers.children["output"]) == 1
        child = buffers.children["input"][0]
        assert attempts == [False] and not child.closed
        assert child.mapping.buf is not None
        assert buffers.children["output"][0].closed
        assert report["binding"] is None and report["metadata"] is None
        assert report["result"] == {
            "status": "unverified", "native_editable": False,
            "issues": [{"code": "strict_recovery_error", "detail": "fixture input close failure"}],
        }
        assert seen.stored == seen.proofs == []
    # The fixture's parent finally owns the failed handle and retries its real
    # close. The first exception must not have silently marked it as closed.
    assert attempts == [False, False]
    assert child.closed and child.mapping.buf is None
    assert buffers.source.buf is None and buffers.output.buf is None
    for name in (buffers.source.name, buffers.output.name):
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


@pytest.mark.parametrize("phase", ["prepare", "proof"])
@pytest.mark.parametrize("failure_kind", ["contract", "capture", "unexpected"])
def test_preparation_and_proof_failures_keep_input_closed_and_report_semantics(
        transport, monkeypatch, phase, failure_kind):
    from backend.core.part_command_errors import CommandContractError
    from backend.core.part_verification_capture import CaptureLimit

    errors = {"contract": CommandContractError("explicit fixture refusal", code="selected_refusal"),
              "capture": CaptureLimit("fixture capture limit"), "unexpected": RuntimeError("fixture failure")}
    codes = {"contract": "selected_refusal", "capture": "strict_recovery_limit",
             "unexpected": "strict_recovery_error"}
    closed_at_failure = []
    with _buffers(transport, monkeypatch, _wire()) as buffers:
        def refuse(_value):
            closed_at_failure.append([child.closed for child in buffers.children["input"]])
            raise errors[failure_kind]

        seen = _fake_preparation(monkeypatch, **{f"on_{phase}": refuse})
        report = _run(transport, buffers)
        assert closed_at_failure == [[True]], "Failure path retained the shared source during preparation/proof"
        assert report["binding"] == _binding()
        assert report["metadata"] == (None if phase == "prepare" else seen.metadata)
        assert report["result"]["status"] == "unverified"
        assert report["result"]["native_editable"] is False
        assert report["result"]["issues"][0]["code"] == codes[failure_kind]
        assert len(seen.stored) == 1
        assert len(seen.proofs) == (phase == "proof")
