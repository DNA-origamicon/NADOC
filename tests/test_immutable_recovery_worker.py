"""Stage-one recovery byte transport: pure preparation, never publication.

Imports of the proposed module stay lazy so this tests-first checkpoint does
not change collection of other targets. Real child/host integration follows in
stage two; no test here starts a process or writes a cache file.
"""

from contextlib import ExitStack
from dataclasses import asdict, replace
from hashlib import sha256
import importlib
import json
import struct
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def transport():
    return importlib.import_module("backend.api.part_immutable_recovery_worker")


@pytest.fixture
def admission():
    from backend.api import doc_context, state
    from backend.api import part_publication_host as host, part_publication_policy as policy
    from backend.api.part_publication_permit import admit_recovery
    from backend.core.part_history_proof import digest

    doc = "__recovery_worker__" + uuid4().hex
    previous = policy.current_configuration()
    with ExitStack() as cleanup:
        token = doc_context.set_current_doc(doc)
        cleanup.callback(doc_context.reset_current_doc, token)
        cleanup.callback(host.configure, previous)
        cleanup.callback(state.drop_doc, doc)
        host.configure(policy.HostPolicyConfiguration(default_mode=previous.default_mode,
            document_modes={**previous.document_modes, doc: "registered_only"}))
        request_hash = digest({"operation": "restore", "expected_revision": 0})
        with state._lock:
            session = state._session()
            handle = admit_recovery(doc, session, request_sha256=request_hash)
        yield SimpleNamespace(doc=doc, handle=handle, session=session, request_hash=request_hash)


def _design(kind="gold", *, annotations=True):
    from backend.core.models import Design
    from backend.core.part_history_contract import create_empty_part
    from backend.core.part_recovery_storage import RECOVERY_PAYLOAD_FIELDS
    from tests.test_part_registered_batch import gold, mixed_commands, prepare, request

    if kind == "empty":
        design = create_empty_part("Recovery worker", "HONEYCOMB")
    else:
        commands = [gold()] if kind == "gold" else mixed_commands()
        design = prepare(body=request(*commands))["candidate"]
    name = "Recovery \u03b1\U0001f9ec\x01 input"
    design.metadata.name = name
    design.recipe_root = design.recipe_root.model_copy(update={"initial_name": name})
    design.id = "content-id-is-independent-of-document-id"
    design.annotations_enabled = annotations
    for entry in design.feature_log:
        for row in [entry, *getattr(entry, "children", [])]:
            for field in RECOVERY_PAYLOAD_FIELDS.intersection(type(row).model_fields):
                setattr(row, field, "poisoned, not executable\x01\x00")
    # Match the established typed JSON boundary, including Mat4x4 floats.
    return Design.model_validate_json(design.model_dump_json())


def _record(admission, payload):
    from backend.api.part_immutable_cache import CacheManifest, StoredRevision

    return StoredRevision(CacheManifest(admission.doc, len(payload), sha256(payload).hexdigest()),
                          payload, None)


def _stored(admission, kind="gold", **kwargs):
    from backend.api.part_immutable_revision import prepare_revision

    return _record(admission, prepare_revision(_design(kind, **kwargs)).payload)


def _packed(transport, admission, record=None):
    record = record or _stored(admission)
    ticket = transport.reserve_input(record, admission=admission.handle)
    parts, binding = transport.encode_input(ticket)
    return ticket, b"".join(parts), binding


def _assert_refused(report):
    assert report["result"]["status"] != "verified", report
    assert report["result"]["native_editable"] is False
    assert report["result"]["issues"]
    assert "candidate" not in report["result"]


def _record_native_calls(monkeypatch, transport):
    from backend.core import part_history_contract

    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("Unadmitted recovery reached native proof")

    monkeypatch.setattr(part_history_contract, "assess_part_history", forbidden)
    if hasattr(transport, "assess_part_history"):
        monkeypatch.setattr(transport, "assess_part_history", forbidden)
    return calls


@pytest.mark.parametrize("kind", ["empty", "gold", "dna_group"])
def test_existing_reference_accepts_native_fixture_without_worker_module(admission, kind):
    from backend.api.part_immutable_recovery_inputs import prepare_stored
    from backend.api.part_immutable_revision import revision_metadata
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history

    record = _stored(admission, kind, annotations=False)
    original = record.payload
    candidate, captured = prepare_stored(record)
    report = assess_part_history(captured, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified" and report["native_editable"] is True, report
    assert report["issues"] == []
    canonical = json.dumps(json.loads(original), sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode()
    assert candidate.payload == original == canonical
    assert record.payload is original
    metadata = revision_metadata(candidate)
    assert metadata.name == "Recovery \u03b1\U0001f9ec\x01 input"
    assert metadata.annotations_enabled is False
    assert metadata.authoring_sha256 == report["authoring_fingerprint"]
    if kind != "empty":
        assert b"poisoned, not executable" in original
        assert metadata.recovery_bytes > 0
        # Ordinary proof deliberately projects history headers, not recovery.
        assert "poisoned, not executable" not in captured.model_dump_json(warnings=False)


@pytest.mark.parametrize("kind", ["empty", "gold", "dna_group"])
@pytest.mark.parametrize("annotations", [False, True])
def test_child_preparation_matches_every_reference_metadata_field_and_native_proof(
        transport, admission, kind, annotations):
    from backend.api.part_immutable_recovery_inputs import prepare_stored
    from backend.api.part_immutable_revision import is_prepared_revision, revision_metadata
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history

    record = _stored(admission, kind, annotations=annotations)
    candidate, captured = prepare_stored(record)
    expected = assess_part_history(captured, execute=execute, dependencies=dependencies)
    ticket, payload, binding = _packed(transport, admission, record)
    report = transport.evaluate_payload(payload)
    assert expected["status"] == "verified", expected
    assert report["binding"] == binding
    assert report["metadata"] == asdict(revision_metadata(candidate))
    assert report["result"] == expected
    assert report["result"]["authoring_fingerprint"] == report["metadata"]["authoring_sha256"]
    assert ticket.payload is record.payload and candidate.payload == record.payload
    assert report["metadata"]["annotations_enabled"] is annotations
    assert report["metadata"]["design_id"] != admission.doc
    assert not is_prepared_revision(report) and not is_prepared_revision(report["metadata"])
    assert not {"candidate", "payload", "_seal", "qualification"}.intersection(report)
    assert json.loads(json.dumps(report, allow_nan=False)) == report


def test_ticket_owns_exact_bytes_and_registered_admission_without_parent_decode(
        transport, admission, monkeypatch):
    from backend.api import part_immutable_recovery_inputs as inputs
    from backend.api import part_immutable_revision as revisions
    from backend.core.models import Design

    record = _stored(admission)
    for module, name in ((inputs, "prepare_stored"), (revisions, "prepare_revision"),
                         (revisions, "_decoded_exact"), (Design, "model_validate_json")):
        monkeypatch.setattr(module, name, lambda *_a, **_k: pytest.fail("Reservation decoded a Design"))
    first, second = (transport.reserve_input(record, admission=admission.handle) for _ in range(2))
    assert first.payload is second.payload is record.payload
    assert first.admission is second.admission is admission.handle
    assert first.id is None and second.id is None
    assert type(first.nonce) is str and first.nonce and first.nonce != second.nonce
    assert not hasattr(first, "__dict__")
    assert getattr(first, "lease", None) is None
    with pytest.raises((AttributeError, TypeError)):
        first.payload = b"changed"
    parts, binding = transport.encode_input(first)
    assert binding["nonce"] == first.nonce
    assert binding["request_sha256"] == admission.request_hash
    assert binding["source_sha256"] == record.manifest.payload_sha256
    assert transport.encode_input(first) == (parts, binding)


@pytest.mark.parametrize("bad", [None, {}, b"{}", "saved-ticket"])
def test_public_values_are_not_private_recovery_tickets(transport, bad):
    with pytest.raises((ValueError, TypeError, AttributeError)):
        transport.encode_input(bad)


@pytest.mark.parametrize("damage", ["missing_admission", "unregistered", "wrong_document", "length", "hash"])
def test_reservation_rejects_unbound_record_before_transport(transport, admission, damage):
    from fastapi import HTTPException
    from backend.api.part_publication_permit import EvaluationAdmission

    record = _stored(admission)
    handle = admission.handle
    if damage == "missing_admission":
        handle = None
    elif damage == "unregistered":
        handle = EvaluationAdmission()
    elif damage == "wrong_document":
        record = replace(record, manifest=replace(record.manifest, doc_id="another-document"))
    elif damage == "length":
        record = replace(record, manifest=replace(record.manifest, payload_bytes=len(record.payload) + 1))
    else:
        record = replace(record, manifest=replace(record.manifest, payload_sha256="0" * 64))
    with pytest.raises((ValueError, TypeError, HTTPException)):
        transport.reserve_input(record, admission=handle)


@pytest.mark.parametrize("field,value", [("operation", "verify"), ("scope_tag", "registered_batch_v1")])
def test_registered_admission_for_another_operation_or_scope_is_not_recovery(
        transport, admission, field, value):
    from backend.api import part_publication_permit as permits

    record = _stored(admission)
    original = permits.admission_context(admission.handle)
    different = replace(original, **{field: value})
    # Register a real host capability with exactly one different context field.
    # An unregistered similarly shaped object would not exercise this guard.
    handle = permits._register(permits._admissions, permits.EvaluationAdmission(), different)
    assert permits.admission_context(handle) is different
    assert different.request_sha256 == original.request_sha256
    with pytest.raises(ValueError, match="registered empty-session admission"):
        transport.reserve_input(record, admission=handle)


@pytest.mark.parametrize("damage", ["version_bool", "version_float", "version_string",
    "length_bool", "length_float", "length_string", "doc_subclass", "hash_subclass"])
def test_manifest_scalars_require_exact_types_even_when_values_compare_equal(
        transport, admission, damage):
    class StringSubclass(str):
        pass

    record = _stored(admission)
    if damage == "length_bool":
        # True == 1: all other raw manifest checks are valid. Reservation must
        # refuse the scalar type without attempting to parse this one-byte body.
        record = _record(admission, b"0")
        changes = {"payload_bytes": True}
    elif damage.startswith("version_"):
        changes = {"storage_version": {"version_bool": True, "version_float": 1.0,
                                        "version_string": "1"}[damage]}
    elif damage == "length_float":
        changes = {"payload_bytes": float(len(record.payload))}
    elif damage == "length_string":
        changes = {"payload_bytes": str(len(record.payload))}
    elif damage == "doc_subclass":
        changes = {"doc_id": StringSubclass(record.manifest.doc_id)}
    else:
        changes = {"payload_sha256": StringSubclass(record.manifest.payload_sha256)}
    record = replace(record, manifest=replace(record.manifest, **changes))
    with pytest.raises(ValueError, match="length or hash"):
        transport.reserve_input(record, admission=admission.handle)


def test_ticket_from_previous_policy_generation_cannot_start_transport(transport, admission):
    from fastapi import HTTPException
    from backend.api import part_publication_host as host, part_publication_policy as policy

    ticket = transport.reserve_input(_stored(admission), admission=admission.handle)
    host.configure(policy.current_configuration())
    with pytest.raises((ValueError, TypeError, HTTPException)):
        transport.encode_input(ticket)


@pytest.mark.parametrize("change", ["session_replacement", "revision"])
def test_actual_session_or_revision_change_invalidates_reserved_ticket(transport, admission, change):
    from backend.api import state

    ticket = transport.reserve_input(_stored(admission), admission=admission.handle)
    if change == "session_replacement":
        assert state.drop_doc(admission.doc)
        with state._lock:
            current = state._session()
        assert current is not admission.session
        assert current.identity != admission.session.identity
        assert current.revision == admission.session.revision == 0
    else:
        with state._lock:
            current = state._sessions[admission.doc]
            current.revision += 1
        assert current is admission.session and current.revision == 1
    assert current.design is None
    with pytest.raises(ValueError, match="stale or its source is busy"):
        transport.encode_input(ticket)
    assert state._sessions[admission.doc] is current and current.design is None


@pytest.mark.parametrize("damage", ["magic", "content", "tail", "truncated", "source_length", "context_length"])
def test_corrupt_frame_refuses_before_native_proof(transport, admission, monkeypatch, damage):
    _ticket, raw, _binding = _packed(transport, admission)
    damaged = bytearray(raw)
    if damage == "magic":
        damaged[0] ^= 1
    elif damage == "content":
        damaged[-1] ^= 1
    elif damage == "tail":
        damaged.extend(b"x")
    elif damage in {"source_length", "context_length"}:
        offset = 8 if damage == "source_length" else 12
        struct.pack_into("!I", damaged, offset, struct.unpack_from("!I", damaged, offset)[0] + 1)
    else:
        del damaged[-1]
    calls = _record_native_calls(monkeypatch, transport)
    _assert_refused(transport.evaluate_payload(bytes(damaged)))
    assert calls == []


@pytest.mark.parametrize("field", ["version", "storage_version"])
@pytest.mark.parametrize("value", [True, 2])
def test_rehashed_context_with_unsupported_version_refuses_before_preparation(
        transport, admission, monkeypatch, field, value):
    from backend.api import part_immutable_recovery_inputs as inputs

    ticket = transport.reserve_input(_stored(admission), admission=admission.handle)
    (header, source, raw), _binding = transport.encode_input(ticket)
    context = json.loads(raw)
    context[field] = value
    raw = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    magic = struct.unpack_from("!8s", header)[0]
    header = struct.pack("!8sII32s32s", magic, len(source), len(raw), sha256(source).digest(), sha256(raw).digest())
    called = []

    def forbidden(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("Unsupported context reached document preparation")

    monkeypatch.setattr(inputs, "prepare_stored", forbidden)
    _assert_refused(transport.evaluate_payload(header + source + raw))
    assert called == []


@pytest.mark.parametrize("damage", ["duplicate", "nonfinite", "noncanonical", "normalization",
                                    "saved_seal", "depth", "unknown_command"])
def test_matching_hash_cannot_bless_invalid_or_normalizing_saved_content(
        transport, admission, monkeypatch, damage):
    raw = _stored(admission).payload
    data = json.loads(raw)
    if damage == "duplicate":
        raw = b'{"id":"duplicate",' + raw[1:]
    elif damage == "nonfinite":
        raw = b'{"not_finite":NaN,' + raw[1:]
    elif damage == "noncanonical":
        raw = json.dumps(data, indent=1).encode()
    elif damage == "depth":
        raw = b'{"value":' + b'[' * 70 + b'0' + b']' * 70 + b'}'
    else:
        if damage == "normalization":
            data.pop("annotations_enabled")
        elif damage == "saved_seal":
            data["_seal"] = {"scope_tag": "registered_batch_v1", "verified": True}
        else:
            data["feature_log"][0]["params"].pop("_proof_version")
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    _ticket, frame, binding = _packed(transport, admission, _record(admission, raw))
    calls = _record_native_calls(monkeypatch, transport)
    result = transport.evaluate_payload(frame)
    assert result["binding"] == binding
    _assert_refused(result)
    assert calls == []


def test_valid_scope_and_saved_recovery_do_not_certify_unlogged_geometry(transport, admission):
    from backend.api.part_immutable_revision import prepare_revision

    design = _design()
    design.nanoparticles[0].diameter_nm = 999.
    raw = prepare_revision(design).payload
    _ticket, frame, _binding = _packed(transport, admission, _record(admission, raw))
    report = transport.evaluate_payload(frame)
    assert report["result"]["status"] == "mismatch"
    _assert_refused(report)
    assert any(issue["code"] == "authoring_state_mismatch" for issue in report["result"]["issues"])


@pytest.mark.parametrize("budget", ["authoring_nodes", "authoring_bytes", "capture_deadline", "pickle_bytes"])
def test_existing_child_admission_limits_remain_before_native_execution(
        transport, admission, monkeypatch, budget):
    from backend.api import part_immutable_recovery_inputs as inputs
    from backend.api import part_immutable_revision as revisions
    from backend.api import part_verification_worker as proof_worker

    _ticket, frame, _binding = _packed(transport, admission)
    if budget in {"authoring_nodes", "authoring_bytes"}:
        original = revisions.admit
        limits = {"max_nodes": 8} if budget == "authoring_nodes" else {"max_bytes": 64}
        monkeypatch.setattr(revisions, "admit", lambda design: original(design, **limits))
    elif budget == "capture_deadline":
        original = inputs.capture
        monkeypatch.setattr(inputs, "capture", lambda design: original(design, seconds=0))
    else:
        # The existing actual pickle byte check is independent of JSON charge.
        monkeypatch.setattr(proof_worker, "MAX_INPUT_BYTES", 32)
    calls = _record_native_calls(monkeypatch, transport)
    _assert_refused(transport.evaluate_payload(frame))
    assert calls == []


@pytest.mark.parametrize("damage", ["nodes", "recovery", "rows"])
def test_full_preparation_cannot_be_replaced_with_native_proof_only(
        transport, admission, monkeypatch, damage):
    from backend.api import part_immutable_revision as revisions

    record = _stored(admission)
    if damage == "nodes":
        monkeypatch.setattr(revisions, "MAX_CANDIDATE_BYTES", 128)
    elif damage == "recovery":
        original = revisions.retained_recovery_bytes
        monkeypatch.setattr(revisions, "retained_recovery_bytes",
            lambda entries, *, max_rows: original(entries, max_rows=max_rows, limit=16))
    else:
        data = json.loads(record.payload)
        data["feature_log"] *= 65
        record = _record(admission, json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    _ticket, frame, _binding = _packed(transport, admission, record)
    calls = _record_native_calls(monkeypatch, transport)
    _assert_refused(transport.evaluate_payload(frame))
    assert calls == []


def test_unstarted_worker_and_plain_metadata_cannot_mint_parent_revision(transport, admission):
    from fastapi import HTTPException
    from backend.api.part_immutable_revision import is_prepared_revision

    ticket, frame, _binding = _packed(transport, admission)
    report = transport.evaluate_payload(frame)
    assert report["result"]["status"] == "verified"
    worker = transport.RecoveryWorker(ticket)
    try:
        assert callable(worker.take_revision)
        with pytest.raises((ValueError, TypeError, AttributeError, HTTPException)):
            worker.take_revision(ticket, admission=admission.handle)
    finally:
        worker.close()
    assert not is_prepared_revision(report["metadata"])
    # Being an exact Python class is not a completed, owned worker observation.
    forged = object.__new__(transport.RecoveryWorker)
    forged.report = report
    forged._closed = True
    with pytest.raises((ValueError, TypeError, AttributeError, HTTPException)):
        forged.take_revision(ticket, admission=admission.handle)
