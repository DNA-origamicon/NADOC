"""Bounded private decoding of a pending record; never publication authority."""

from hashlib import sha256
import json

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api.part_immutable_cache import StoredRevision
from backend.api.part_immutable_revision import _check_structure, prepare_revision
from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import capture


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)


def _reject(detail):
    raise CommandContractError(detail, code="strict_cache_invalid")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject("Saved strict content contains duplicate JSON fields")
        result[key] = value
    return result


def _nonfinite(_value):
    _reject("Saved strict content requires finite JSON numbers")


def prepare_stored(stored, *, checkpoint=lambda: None):
    """Return one scope-only seal and an isolated ordinary proof projection.

    No byte-to-seal shortcut exists: untrusted JSON must pass current scope and
    complete canonical roundtrip checks. Recovery text is never replay evidence.
    This work and its transient decode graph belong outside the state lock.
    """
    checkpoint()
    if (type(stored) is not StoredRevision or type(stored.payload) is not bytes
            or not 0 < len(stored.payload) <= MAX_CANDIDATE_BYTES
            or len(stored.payload) != stored.manifest.payload_bytes
            or sha256(stored.payload).hexdigest() != stored.manifest.payload_sha256):
        _reject("Saved strict content does not match its bounded manifest")
    try:
        data = json.loads(stored.payload, object_pairs_hook=_unique, parse_constant=_nonfinite)
        _check_structure(data, checkpoint)
        private = Design.model_validate(data)
        del data
        candidate = prepare_revision(private, checkpoint=checkpoint)
        if candidate.payload != stored.payload:
            _reject("Saved strict content changes under current full-document decoding")
        captured = capture(private)
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, CommandContractError):
            raise
        _reject(f"Saved strict content is unsupported: {str(error)[:1024]}")
    checkpoint()
    return candidate, captured
