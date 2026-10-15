"""Private immutable strict-part content; a scope seal grants no write/proof.

Preparation and every materialization belong outside the shared state lock.
Only bytes and small frozen indexes survive preparation; no mutable Design is
retained or cached. This module is not a file-restore or publication endpoint.
"""

from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from itertools import chain
import json
from math import isfinite
from types import SimpleNamespace
from weakref import ref

from pydantic import BaseModel

from backend.api.part_batch_publication_scope import MAX_PUBLIC_HISTORY_ROWS, admit_batch_source
from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
from backend.api.part_recovery_budget import retained_recovery_bytes
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import AUTHORING_FIELDS, digest
from backend.core.part_verification_capture import CaptureLimit, admit


RECIPE_FIELDS = frozenset({"recipe_root", "feature_log", "input_sources",
                           "feature_log_cursor", "feature_log_sub_cursor"})
_SCOPE = "registered_batch_v1"
_TOKEN = object()
_MAX_DEPTH = 64


@dataclass(frozen=True, slots=True)
class RevisionMetadata:
    design_id: str
    name: str
    lattice_type: str
    payload_bytes: int
    authoring_sha256: str
    recipe_sha256: str
    history_rows: int
    recovery_bytes: int
    storage_version: int = 1
    scope_tag: str = _SCOPE


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False, init=False)
class StrictPartRevision:
    payload: bytes = field(repr=False)
    _metadata: RevisionMetadata
    _seal: object = field(repr=False)

    def __init__(self):
        raise TypeError("Strict revisions require the private preparation factory")


@dataclass(frozen=True, slots=True, eq=False)
class _ScopeSeal:
    token: object
    owner: ref
    payload: bytes
    metadata: RevisionMetadata


def _reject(detail, *, code="invalid_revision_payload"):
    raise CommandContractError(detail, code=code)


def is_prepared_revision(value):
    """Constant-size ownership check, never a replay or scientific verdict."""
    if type(value) is not StrictPartRevision:
        return False
    try:
        seal = value._seal
        metadata = value._metadata
        return (type(seal) is _ScopeSeal and seal.token is _TOKEN and seal.owner() is value
            and type(value.payload) is bytes and seal.payload is value.payload
            and type(metadata) is RevisionMetadata and seal.metadata is metadata
            and metadata.storage_version == 1 and metadata.scope_tag == _SCOPE
            and metadata.payload_bytes == len(value.payload) <= MAX_CANDIDATE_BYTES)
    except AttributeError:
        return False


def _require_revision(value):
    if not is_prepared_revision(value):
        _reject("Expected a privately prepared revision", code="invalid_revision_handle")


def revision_metadata(value):
    _require_revision(value)
    return value._metadata


def _model_schema(value):
    if (set(value.__dict__) != set(type(value).model_fields)
            or getattr(value, "__pydantic_extra__", None)):
        _reject("Immutable revision cannot classify this model schema")


def _scalar_metadata(candidate):
    for name, value in (("design identity", candidate.id), ("name", getattr(candidate.metadata, "name", None))):
        if type(value) is not str or not 1 <= len(value) <= 1024:
            _reject(f"Immutable revision {name} must be a bounded nonempty string")


def _check_structure(value, checkpoint):
    """Bound full model serialization separately from ordinary authoring admit.

    Recovery text is retained under its existing cumulative 8 MB cap. Structural
    work here is charged against the fixed 16 MB transport allowance, without
    expanding the ordinary 30k-node/2 MB authoring profile. Encoding performs the
    exact escaped-JSON byte check before any model decode.
    """
    pending = [(value, 0, False)]
    active = set()
    remaining = MAX_CANDIDATE_BYTES
    while pending:
        checkpoint()
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        remaining -= 16
        if remaining < 0:
            raise CaptureLimit("Immutable revision exceeds its full transport allowance")
        if depth > _MAX_DEPTH:
            _reject("Immutable revision exceeds its JSON depth allowance")
        if isinstance(item, Enum):
            item = item.value
        if type(item) is str:
            remaining -= len(item) * (1 if item.isascii() else 4)
        elif item is None or type(item) is bool:
            continue
        elif type(item) is int:
            if item.bit_length() > 64:
                _reject("Immutable revision integers must fit the existing JSON input range")
        elif type(item) is float:
            if not isfinite(item):
                _reject("Immutable revision numbers must be finite")
        elif isinstance(item, BaseModel) or type(item) in {dict, list, tuple}:
            if id(item) in active:
                _reject("Immutable revision cannot contain a cyclic model or JSON value")
            if isinstance(item, BaseModel):
                _model_schema(item)
                children = item.__dict__.values()
                child_count = len(children)
            elif type(item) is dict:
                child_count = len(item) * 2
                if 16 * (child_count + len(pending)) > remaining:
                    raise CaptureLimit("Immutable revision exceeds its full structural allowance")
                if any(type(key) is not str for key in item):
                    _reject("Immutable revision JSON object keys must be strings")
                children = chain(item.keys(), item.values())
            else:
                children = item
                child_count = len(children)
            if 16 * (child_count + len(pending)) > remaining:
                raise CaptureLimit("Immutable revision exceeds its full structural allowance")
            active.add(id(item))
            pending.append((item, depth, True))
            pending.extend((child, depth + 1, False) for child in children)
        else:
            _reject("Immutable revision permits only model fields and JSON values")
        if remaining < 0:
            raise CaptureLimit("Immutable revision exceeds its full transport allowance")


def _canonical_payload(data, checkpoint):
    # Same canonical JSON settings as the existing authoring/recipe digest.
    # This encodes the complete ordinary Design, not another recipe format.
    output = BytesIO()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(data):
        checkpoint()
        encoded = chunk.encode("utf-8")
        if output.tell() + len(encoded) > MAX_CANDIDATE_BYTES:
            raise CaptureLimit("Immutable revision exceeds the existing candidate byte ceiling")
        output.write(encoded)
    return output.getvalue()


def _decoded_exact(payload, checkpoint):
    checkpoint()
    try:
        decoded = Design.model_validate_json(payload)
        checkpoint()
        roundtrip = _canonical_payload(decoded.model_dump(mode="json", serialize_as_any=True, warnings="error"), checkpoint)
    except (ValueError, TypeError) as error:
        if isinstance(error, (CommandContractError, CaptureLimit)):
            raise
        _reject(f"Immutable revision cannot decode its document: {str(error)[:2048]}")
    if roundtrip != payload:
        _reject("Immutable revision decoding changed the full document",
                code="revision_decode_changed_document")
    return decoded


def prepare_revision(candidate, *, checkpoint=lambda: None):
    """Seal a private host candidate's storage scope, never its reproducibility.

    No mutable alias may be shared with an active writer during this function.
    The caller must separately establish native composition/independent proof
    and source-bound publication authority through the existing job contracts.
    """
    checkpoint()
    if type(candidate) is not Design:
        _reject("Revision preparation needs a private exact Design model")
    _model_schema(candidate)
    _scalar_metadata(candidate)
    admit_batch_source(candidate)
    admit(candidate)  # Existing ordinary authoring node/byte bounds, unchanged.
    _check_structure(candidate, checkpoint)
    # Reuse the batch's existing aggregate authored work contract, with no new
    # commands or executor dispatch. This does not execute geometry builders.
    from backend.api.part_registered_batch import _reserve_work

    _reserve_work(candidate, SimpleNamespace(commands=()))
    checkpoint()
    try:
        data = candidate.model_dump(mode="json", serialize_as_any=True, warnings="error")
        payload = _canonical_payload(data, checkpoint)
    except (ValueError, TypeError) as error:
        if isinstance(error, (CommandContractError, CaptureLimit)):
            raise
        _reject(f"Immutable revision cannot serialize its document: {str(error)[:2048]}")
    decoded = _decoded_exact(payload, checkpoint)
    # Full-byte equality above is stronger than the two projections, including
    # document identity, presentation flags and every saved recovery field.
    metadata = RevisionMetadata(
        design_id=decoded.id, name=decoded.metadata.name, lattice_type=decoded.lattice_type.value,
        payload_bytes=len(payload), authoring_sha256=digest({name: data[name] for name in AUTHORING_FIELDS}),
        recipe_sha256=digest({name: data[name] for name in RECIPE_FIELDS}),
        history_rows=len(decoded.feature_log) + sum(len(entry.children) for entry in decoded.feature_log
                                                   if entry.feature_type == "routing-cluster"),
        recovery_bytes=retained_recovery_bytes(decoded.feature_log, max_rows=MAX_PUBLIC_HISTORY_ROWS),
    )
    checkpoint()
    revision = object.__new__(StrictPartRevision)
    object.__setattr__(revision, "payload", payload)
    object.__setattr__(revision, "_metadata", metadata)
    object.__setattr__(revision, "_seal", _ScopeSeal(_TOKEN, ref(revision), payload, metadata))
    return revision


def materialize_revision(revision, *, checkpoint=lambda: None):
    """Decode a fresh, independent full Design outside all shared state locks."""
    _require_revision(revision)
    return _decoded_exact(revision.payload, checkpoint)
