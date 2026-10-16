"""Private bounded recovery preparation and proof in one disposable child.

Stage one only: this transport has no host publication or revision-seal factory.
The child executes the existing preparation and proof implementations. Its JSON
metadata is data, never a serialized scope seal or a publication capability.
"""

from dataclasses import asdict, dataclass, field, fields
from hashlib import sha256
import json
from multiprocessing.shared_memory import SharedMemory
import os
import pickle
from re import fullmatch
from secrets import token_hex
import struct
from weakref import ref

from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
from backend.api.part_verification_worker import (
    MAX_RESULT_BYTES, RESULT_HEADER_BYTES, VerificationWorker, WorkerLimit,
    _BoundedInput, _result_bytes, failure,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import CaptureLimit


MAGIC = b"NADOC-R1"
_HEADER = struct.Struct("!8sII32s32s")
MAX_HEADER_BYTES = 4096
MAX_INPUT_BYTES = _HEADER.size + MAX_CANDIDATE_BYTES + MAX_HEADER_BYTES
_TOKEN = object()
_OBSERVATION = object()
_CONTEXT_FIELDS = frozenset({"version", "doc_id", "session_identity", "source_revision",
    "policy_generation", "request_sha256", "nonce", "storage_version"})
_BINDING_FIELDS = frozenset({"version", "source_sha256", "context_sha256", "request_sha256", "nonce"})
_METADATA_FIELDS = frozenset({"design_id", "name", "lattice_type", "payload_bytes",
    "authoring_sha256", "recipe_sha256", "history_rows", "recovery_bytes",
    "annotations_enabled", "preservation_version", "preserved_document_sha256",
    "storage_version", "scope_tag"})


def _reject(detail):
    raise ValueError(detail)


def _hash(value):
    return type(value) is str and fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _context(value):
    """Validate the tiny fixed wire header, not any document or authority."""
    from backend.api.document_identity import require_document_identity

    if type(value) is not dict or set(value) != _CONTEXT_FIELDS:
        _reject("Invalid recovery transport context fields")
    if (type(value["version"]) is not int or value["version"] != 1
            or type(value["storage_version"]) is not int or value["storage_version"] != 1
            or type(value["session_identity"]) is not str or not 1 <= len(value["session_identity"]) <= 128
            or not _integer(value["source_revision"], 2 ** 63 - 1)
            or not _integer(value["policy_generation"], 2 ** 63 - 1)
            or not _hash(value["request_sha256"])
            or type(value["nonce"]) is not str or fullmatch(r"[0-9a-f]{32}", value["nonce"]) is None):
        _reject("Invalid recovery transport context values")
    require_document_identity(value["doc_id"])
    return value


def _current_admission(admission):
    from backend.api import state
    from backend.api.part_publication_permit import admission_context
    from backend.api.part_publication_policy import resolve

    context = admission_context(admission)
    if (context is None or context.operation != "restore" or context.scope_tag != "strict_recovery_v1"
            or context.source() is not None or not _hash(context.request_sha256)):
        _reject("Recovery transport requires its registered empty-session admission")
    policy = resolve(context.doc_id)
    if (not policy.strict or policy.generation != context.policy_generation
            or state.verification_source_matches(context.doc_id, None, context.source_revision,
                blocking=False, expected_session_identity=context.session_identity,
                expected_policy_generation=context.policy_generation) is not True):
        _reject("Recovery transport admission is stale or its source is busy")
    return context


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False, init=False)
class RecoveryInput:
    payload: bytes = field(repr=False)
    admission: object
    nonce: str
    id: None
    _reservation: object = field(repr=False)

    def __init__(self):
        raise TypeError("Recovery inputs require a private host reservation")


@dataclass(frozen=True, slots=True, eq=False)
class _Reservation:
    token: object
    owner: object
    payload: bytes = field(repr=False)
    admission: object
    context: object
    nonce: str
    source_sha256: str


def _reservation(ticket):
    if type(ticket) is not RecoveryInput:
        _reject("Expected a private recovery input ticket")
    value = getattr(ticket, "_reservation", None)
    if (type(value) is not _Reservation or value.token is not _TOKEN or value.owner() is not ticket
            or ticket.payload is not value.payload or ticket.admission is not value.admission
            or ticket.nonce != value.nonce or ticket.id is not None):
        _reject("Recovery input does not own its original reservation")
    return value


def reserve_input(stored, *, admission):
    """Retain bounded exact bytes and a current admission; never decode a model."""
    from backend.api.part_immutable_cache import CacheManifest, StoredRevision

    context = _current_admission(admission)
    if (type(stored) is not StoredRevision or type(stored.manifest) is not CacheManifest
            or type(stored.payload) is not bytes or not 0 < len(stored.payload) <= MAX_CANDIDATE_BYTES):
        _reject("Recovery transport needs a bounded exact stored record")
    manifest = stored.manifest
    if (type(manifest.storage_version) is not int or manifest.storage_version != 1
            or type(manifest.payload_bytes) is not int or manifest.payload_bytes != len(stored.payload)
            or type(manifest.doc_id) is not str or manifest.doc_id != context.doc_id
            or not _hash(manifest.payload_sha256)
            or sha256(stored.payload).hexdigest() != manifest.payload_sha256):
        _reject("Recovery record does not match its admitted document, length or hash")
    nonce = token_hex(16)
    _context({"version": 1, "storage_version": 1, "doc_id": context.doc_id,
        "session_identity": context.session_identity, "source_revision": context.source_revision,
        "policy_generation": context.policy_generation, "request_sha256": context.request_sha256,
        "nonce": nonce})
    ticket = object.__new__(RecoveryInput)
    for name, value in (("payload", stored.payload), ("admission", admission), ("nonce", nonce), ("id", None)):
        object.__setattr__(ticket, name, value)
    object.__setattr__(ticket, "_reservation", _Reservation(_TOKEN, ref(ticket), stored.payload,
        admission, context, nonce, manifest.payload_sha256))
    return ticket


def encode_input(ticket):
    """Build a fixed, bounded frame using the original immutable source bytes."""
    reservation = _reservation(ticket)
    context = _current_admission(ticket.admission)
    if context is not reservation.context:
        _reject("Recovery input admission changed after reservation")
    data = _context({"version": 1, "storage_version": 1, "doc_id": context.doc_id,
        "session_identity": context.session_identity, "source_revision": context.source_revision,
        "policy_generation": context.policy_generation, "request_sha256": context.request_sha256,
        "nonce": ticket.nonce})
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if not 0 < len(raw) <= MAX_HEADER_BYTES:
        _reject("Recovery context exceeds its fixed header allowance")
    source_hash, context_hash = bytes.fromhex(reservation.source_sha256), sha256(raw).digest()
    header = _HEADER.pack(MAGIC, len(ticket.payload), len(raw), source_hash, context_hash)
    binding = {"version": 1, "source_sha256": source_hash.hex(), "context_sha256": context_hash.hex(),
               "request_sha256": context.request_sha256, "nonce": ticket.nonce}
    return (header, ticket.payload, raw), binding


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject("Recovery transport context has duplicate fields")
        result[key] = value
    return result


def _frame(payload):
    if type(payload) is not bytes or not _HEADER.size < len(payload) <= MAX_INPUT_BYTES:
        _reject("Invalid recovery frame size")
    magic, size, context_size, source_hash, context_hash = _HEADER.unpack_from(payload)
    if (magic != MAGIC or not 0 < size <= MAX_CANDIDATE_BYTES or not 0 < context_size <= MAX_HEADER_BYTES
            or _HEADER.size + size + context_size != len(payload)):
        _reject("Invalid recovery frame header")
    source = payload[_HEADER.size:_HEADER.size + size]
    raw = payload[_HEADER.size + size:]
    if sha256(source).digest() != source_hash or sha256(raw).digest() != context_hash:
        _reject("Recovery frame input digest mismatch")
    context = _context(json.loads(raw, object_pairs_hook=_unique,
        parse_constant=lambda _value: _reject("Recovery context requires finite JSON")))
    if json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() != raw:
        _reject("Recovery context is not canonical")
    binding = {"version": 1, "source_sha256": source_hash.hex(), "context_sha256": context_hash.hex(),
               "request_sha256": context["request_sha256"], "nonce": context["nonce"]}
    return source, context, binding


def evaluate_payload(payload):
    """Child-only preparation and proof; returned JSON never grants a seal."""
    binding = metadata = None
    try:
        source, context, binding = _frame(payload)
        from backend.api.part_immutable_cache import CacheManifest, StoredRevision
        from backend.api.part_immutable_recovery_inputs import prepare_stored
        from backend.api.part_immutable_revision import revision_metadata

        # The reference preparation never uses its lease. Actual file ownership
        # remains entirely in the parent, outside the child protocol.
        stored = StoredRevision(CacheManifest(context["doc_id"], len(source), binding["source_sha256"]),
                                source, None)
        candidate, captured = prepare_stored(stored)
        del stored, source, payload
        # Preserve the actual existing pickle ceiling, independently of capture
        # accounting, and the old private serialize/deserialize handoff semantics.
        with _BoundedInput() as stream:
            pickle.dump(captured, stream, protocol=pickle.HIGHEST_PROTOCOL)
            proof_input = pickle.loads(stream.getvalue())
        del captured
        metadata = asdict(revision_metadata(candidate))
        del candidate
        from backend.api.part_proof_commands import dependencies, execute
        from backend.core.part_history_contract import assess_part_history

        result = assess_part_history(proof_input, execute=execute, dependencies=dependencies)
    except CommandContractError as error:
        result = {"status": "unverified", "native_editable": False, "issues": [error.as_issue()]}
    except CaptureLimit as error:
        result = failure("strict_recovery_limit", error)
    except WorkerLimit as error:
        result = failure("worker_input_limit", error)
    except Exception as error:
        result = failure("strict_recovery_error", error)
    return {"issues": [], "binding": binding, "metadata": metadata, "result": result}


def _binding(value):
    if (type(value) is not dict or set(value) != _BINDING_FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or any(not _hash(value[key]) for key in ("source_sha256", "context_sha256", "request_sha256"))
            or type(value["nonce"]) is not str or fullmatch(r"[0-9a-f]{32}", value["nonce"]) is None):
        _reject("Invalid recovery result binding")
    return tuple(sorted(value.items()))


def _metadata(value, payload_size):
    from backend.api.part_batch_publication_scope import MAX_PUBLIC_HISTORY_ROWS
    from backend.api.part_immutable_preservation import PRESERVATION_VERSION
    from backend.api.part_immutable_revision import RevisionMetadata
    from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES

    if (type(value) is not dict or set(value) != _METADATA_FIELDS
            or {field.name for field in fields(RevisionMetadata)} != _METADATA_FIELDS):
        _reject("Recovery result has an unsupported metadata schema")
    if (any(type(value[key]) is not str or not 1 <= len(value[key]) <= 1024 for key in ("design_id", "name"))
            or type(value["lattice_type"]) is not str or value["lattice_type"] not in {"HONEYCOMB", "SQUARE"}
            or not _integer(value["payload_bytes"], MAX_CANDIDATE_BYTES) or value["payload_bytes"] != payload_size
            or any(not _hash(value[key]) for key in ("authoring_sha256", "recipe_sha256", "preserved_document_sha256"))
            or not _integer(value["history_rows"], MAX_PUBLIC_HISTORY_ROWS)
            or not _integer(value["recovery_bytes"], MAX_RECOVERY_BYTES)
            or type(value["annotations_enabled"]) is not bool
            or type(value["preservation_version"]) is not int or value["preservation_version"] != PRESERVATION_VERSION
            or type(value["storage_version"]) is not int or value["storage_version"] != 1
            or type(value["scope_tag"]) is not str or value["scope_tag"] != "registered_batch_v1"):
        _reject("Recovery result metadata exceeds its reviewed scope")
    return RevisionMetadata(**value)


@dataclass(frozen=True, slots=True, eq=False, init=False)
class _Completion:
    token: object
    owner: object
    ticket: object
    admission: object
    binding: tuple
    metadata: object

    def __init__(self):
        raise TypeError("Recovery completion is a private host observation")


def _evaluate(input_name, input_size, output_name):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    source = None
    output = SharedMemory(name=output_name)
    try:
        try:
            if not _HEADER.size < input_size <= MAX_INPUT_BYTES:
                _reject("Invalid recovery input buffer size")
            source = SharedMemory(name=input_name)
            report = evaluate_payload(bytes(source.buf[:input_size]))
        except BaseException as error:
            report = {"issues": [], "binding": None, "metadata": None,
                      "result": failure("strict_recovery_error", error)}
        # Binding + metadata consume part of the unchanged 2 MB output ceiling.
        fallback = {"issues": [], "binding": report.get("binding"), "metadata": None,
                    "result": failure("result_limit")}
        encoded = _result_bytes(report, limit=MAX_RESULT_BYTES, limit_result=fallback)
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        if source is not None:
            source.close()
        output.close()


class RecoveryWorker(VerificationWorker):
    """One child and private completion; stage one cannot create a revision."""

    def __init__(self, ticket):
        parts, binding = encode_input(ticket)
        self._ticket = ticket
        self._binding = _binding(binding)
        self._completion = None
        self._result_read = False
        self._initialize_input(parts, _target=_evaluate, _result_limit=MAX_RESULT_BYTES,
                               _name="nadoc-part-recovery")

    def result(self):
        if self._result_read:
            _reject("Recovery completion has already been observed")
        report = self._read_result()
        self._result_read = True
        if self._process.exitcode != 0:
            return failure("worker_exited")
        if (type(report) is not dict or set(report) != {"issues", "binding", "metadata", "result"}
                or report["issues"] != [] or _binding(report["binding"]) != self._binding):
            _reject("Recovery result does not match its admitted input")
        result = report["result"]
        if (type(result) is not dict or type(result.get("issues")) is not list
                or type(result.get("native_editable")) is not bool
                or result.get("status") not in {"verified", "reproduced_import", "failed", "mismatch", "unverified"}
                or {"candidate", "payload", "_seal", "qualification"}.intersection(result)):
            _reject("Invalid recovery proof result")
        metadata = _metadata(report["metadata"], len(self._ticket.payload)) if report["metadata"] is not None else None
        if result["status"] == "verified":
            if (metadata is None or result["native_editable"] is not True or result["issues"]
                    or result.get("scope") != "part" or type(result.get("contract_version")) is not int
                    or result["contract_version"] != 1 or result.get("proof_coverage") != "versioned_commands"
                    or not _hash(result.get("authoring_fingerprint"))
                    or result["authoring_fingerprint"] != metadata.authoring_sha256):
                _reject("Recovery proof does not qualify its exact prepared metadata")
            observation = object.__new__(_Completion)
            for name, value in (("token", _OBSERVATION), ("owner", ref(self)), ("ticket", self._ticket),
                                ("admission", self._ticket.admission), ("binding", self._binding), ("metadata", metadata)):
                object.__setattr__(observation, name, value)
            self._completion = observation
        elif result["native_editable"]:
            _reject("Unverified recovery cannot claim native editability")
        return result

    def take_revision(self, ticket, *, admission):
        """Explicitly unavailable until separately tested host-seal integration.

        A valid observation alone is not a scope seal. Stage two must also require
        closed-worker ownership, exact ticket/admission, one-shot consumption and
        the host's final deadline/context checks before installing a local seal.
        """
        raise CommandContractError("Recovery worker revision sealing is not integrated",
                                   code="recovery_seal_unavailable")
