"""Private full-byte transport; source projection runs inside the owned child.

This format is never accepted from HTTP or disk. A sealed source is scope
evidence only: the child still runs ordinary admission and native regeneration.
Full storage bytes (16 MB) and operation bytes (256 KB) have separate ceilings;
ordinary authoring remains 30k nodes / 2 MB / 25 ms. Recovery is never replay input.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from multiprocessing.shared_memory import SharedMemory
import os
import struct
from time import monotonic

from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES, evaluate_native as native_evaluate
from backend.api.part_immutable_storage import require_sealed
from backend.api.part_verification_worker import RESULT_HEADER_BYTES, VerificationWorker, _result_bytes, failure
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, validate_operation_input
from backend.core.part_verification_capture import CaptureLimit


MAGIC = b"NADOC-I1"
_HEADER = struct.Struct("!8sII32s32s")
MAX_INPUT_BYTES = _HEADER.size + MAX_CANDIDATE_BYTES + MAX_OPERATION_BYTES
_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ImmutableInput:
    source: object
    id: str
    _token: object

    def __init__(self):
        raise TypeError("Immutable worker inputs require a private sealed source")


def reserve_input(source):
    return _reserve_input(source, scope="registered_batch_v1")


def _reserve_input(source, *, scope):
    metadata = require_sealed(source)
    if metadata.scope_tag != scope:
        raise ValueError(f"This worker requires its admitted storage scope: {scope}")
    value = object.__new__(ImmutableInput)
    for key, item in (("source", source), ("id", metadata.design_id), ("_token", _TOKEN)):
        object.__setattr__(value, key, item)
    return value


def is_immutable_input(value):
    return type(value) is ImmutableInput and getattr(value, "_token", None) is _TOKEN


def encode_input(ticket, operation):
    return _encode_input(ticket, operation, scope="registered_batch_v1", magic=MAGIC)


def _encode_input(ticket, operation, *, scope, magic):
    """Own the bounded operation and retain existing source bytes, without decode."""
    if not is_immutable_input(ticket):
        raise ValueError("Strict byte transport requires a private source reservation")
    metadata = require_sealed(ticket.source)
    if ticket.id != metadata.design_id or metadata.scope_tag != scope:
        raise ValueError("Immutable source reservation changed identity")
    validate_operation_input(operation)
    raw = json.dumps(operation, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if not 0 < len(raw) <= MAX_OPERATION_BYTES:
        raise ValueError("Strict worker operation exceeds its byte ceiling")
    source = ticket.source.payload
    source_hash, operation_hash = sha256(source).digest(), sha256(raw).digest()
    header = _HEADER.pack(magic, len(source), len(raw), source_hash, operation_hash)
    binding = {"version": 1, "source_sha256": source_hash.hex(), "operation_sha256": operation_hash.hex()}
    return (header, source, raw), binding


def _frame(payload, *, expected_magic=MAGIC):
    if type(payload) is not bytes or not _HEADER.size < len(payload) <= MAX_INPUT_BYTES:
        raise ValueError("Invalid strict worker frame size")
    magic, source_size, operation_size, source_hash, operation_hash = _HEADER.unpack_from(payload)
    if (magic != expected_magic or not 0 < source_size <= MAX_CANDIDATE_BYTES
            or not 0 < operation_size <= MAX_OPERATION_BYTES
            or _HEADER.size + source_size + operation_size != len(payload)):
        raise ValueError("Invalid strict worker frame header")
    source_bytes = payload[_HEADER.size:_HEADER.size + source_size]
    operation_bytes = payload[_HEADER.size + source_size:]
    if sha256(source_bytes).digest() != source_hash or sha256(operation_bytes).digest() != operation_hash:
        raise ValueError("Strict worker input digest mismatch")
    binding = {"version": 1, "source_sha256": source_hash.hex(), "operation_sha256": operation_hash.hex()}
    return source_bytes, operation_bytes, binding


def _project(source_bytes, operation_bytes):
    operation = json.loads(operation_bytes)
    validate_operation_input(operation)
    if (type(operation) is not dict or set(operation) != {"request", "header"}
            or type(operation["header"]) is not dict
            or set(operation["header"]) != {"identity", "timestamp", "source_revision", "source_design_id"}):
        raise ValueError("Invalid strict worker operation envelope")
    from backend.api.part_evaluation import EvaluationRequest
    from backend.api.part_immutable_revision import _decoded_exact
    from backend.api.part_batch_publication_scope import admit_batch_source
    from backend.core.part_capture_inputs import visit_inputs

    request = EvaluationRequest.model_validate(operation["request"])
    header = operation["header"]
    revision = header["source_revision"]
    if (request.operation not in {"batch", "verify"} or type(revision) is not int or revision < 0
            or any(type(header[key]) is not str or not header[key] for key in ("identity", "timestamp", "source_design_id"))
            or (request.expected_revision is not None and request.expected_revision != revision)):
        raise ValueError("Strict worker operation has an unsupported captured context")
    private = _decoded_exact(source_bytes, lambda: None)
    if (private.id != header["source_design_id"] or (request.operation == "batch" and (
            request.batch.expected_design_id != private.id or request.batch.expected_revision != revision))):
        raise ValueError("Strict worker request belongs to a different source")
    # Host availability was checked before admission. No child request or
    # serialized flag can turn on the host gate. Recheck structural scope here.
    deadline = monotonic() + 0.025
    admit_batch_source(private, request.batch.commands if request.operation == "batch" else ())
    captured = visit_inputs(private, max_nodes=30_000, max_bytes=2_000_000,
        seconds=max(0, deadline - monotonic()), preserve_entry_types=True,
        copy_inputs=False, retain_owned=True)
    return captured, operation


def decode_input(payload):
    """Child-only exact decode and ordinary owned projection, before any executor."""
    source, operation, binding = _frame(payload)
    captured, operation = _project(source, operation)
    return captured, operation, binding


def evaluate_payload(payload):
    binding = None
    try:
        source, operation, binding = _frame(payload)
        del payload
        captured, operation = _project(source, operation)
        del source
    except CommandContractError as error:
        result = {"status": "unverified", "native_editable": False, "issues": [error.as_issue()]}
    except CaptureLimit as error:
        result = failure("strict_worker_capture_limit", error)
    except Exception as error:
        result = failure("strict_worker_input", error)
    else:
        try:
            result = native_evaluate(captured, operation)
        except Exception as error:
            result = failure("evaluation_error", error)
    return {"issues": [], "binding": binding, "result": result}


def _evaluate(input_name, input_size, output_name):
    _run_framed(input_name, input_size, output_name, evaluate_payload)


def _owned_input(input_name, input_size):
    if not _HEADER.size < input_size <= MAX_INPUT_BYTES:
        raise ValueError("Invalid strict worker buffer size")
    source = SharedMemory(name=input_name)
    try:
        return bytes(source.buf[:input_size])
    finally:
        source.close()


def _run_framed(input_name, input_size, output_name, evaluator):
    """Fixed child targets share resource cleanup; no request selects evaluator."""
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    output = SharedMemory(name=output_name)
    try:
        try:
            # No extra local payload alias survives during evaluation. The
            # evaluator can release the full frame after splitting its inputs.
            result = evaluator(_owned_input(input_name, input_size))
        except BaseException as error:
            result = {"issues": [], "binding": None, "result": failure("strict_worker_input", error)}
        encoded = _result_bytes(result, limit=MAX_CANDIDATE_BYTES,
            limit_result={"issues": [], "binding": result.get("binding"), "result": failure("result_limit")})
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        output.close()


class ImmutableEvaluationWorker(VerificationWorker):
    def __init__(self, ticket, operation):
        parts, self.binding = encode_input(ticket, operation)
        self._initialize_input(parts, _target=_evaluate, _result_limit=MAX_CANDIDATE_BYTES,
                               _name="nadoc-immutable-part-evaluation")

    def result(self):
        report = self._read_result()
        if self._process.exitcode not in (None, 0):
            # _read_result observed a reaped nonzero exit. This host observation
            # is distinct from accepting bindingless JSON supplied by a child.
            return failure("worker_exited")
        if report.get("binding") != self.binding:
            raise ValueError("Strict worker result binding does not match its admitted input")
        result = report.get("result")
        if (type(result) is not dict or type(result.get("issues")) is not list
                or result.get("status") not in {"ready", "verified", "reproduced_import", "failed", "mismatch", "unverified"}
                or (result["status"] == "ready" and type(result.get("candidate")) is not dict)):
            raise ValueError("Invalid strict worker result")
        return result
