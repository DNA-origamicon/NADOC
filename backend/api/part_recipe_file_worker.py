"""Disposable recovery worker transporting original bytes and exact output text.

Only the server constructs the bounded pickle envelope. User file bytes are a
bytes value inside it, never interpreted as pickle. Parsing, source resolution,
native replay and server-side document encoding all happen in the child.
"""

from hashlib import sha256
from multiprocessing.shared_memory import SharedMemory
import os
import pickle
import struct
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES, native_thread_limit
from backend.api.part_recipe_file_recovery import FileRecoveryRequest
from backend.api.part_verification_worker import (
    MAX_INPUT_BYTES, RESULT_HEADER_BYTES, VerificationWorker, WorkerLimit, _result_bytes, failure,
)
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_recipe_file import MAX_FILE_BYTES


MAX_RESULT_BYTES = MAX_CANDIDATE_BYTES
_LIMIT_MARKER = {"recovered_file_limit": True}


class _InspectOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: StrictInt = Field(ge=1, le=1)
    operation: Literal["inspect"]


class _RecoverOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: StrictInt = Field(ge=1, le=1)
    operation: Literal["recover"]
    request: FileRecoveryRequest


_OPERATION = TypeAdapter(Annotated[_InspectOperation | _RecoverOperation, Field(discriminator="operation")])


def parse_operation(operation):
    """Bound and detach strict JSON metadata before allocating child transport."""
    validate_operation_input(operation)
    return _OPERATION.validate_python(operation, strict=True).model_dump(mode="json")


def _raw_bytes(raw):
    if type(raw) is not bytes:
        raise ValueError("Recipe file worker requires immutable original bytes")
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise WorkerLimit("Recipe file exceeds the recovery input byte limit")


def evaluate_file(raw, operation):
    """Use the same bounded numerical-thread policy as ordinary native jobs."""
    with native_thread_limit():
        from backend.api.part_recipe_file_recovery import inspect_recipe_file, recover_recipe_file

        if operation["operation"] == "inspect":
            return inspect_recipe_file(raw)
        return recover_recipe_file(raw, operation["request"])


def _read_request(input_name, input_size):
    source = SharedMemory(name=input_name)
    try:
        if (type(input_size) is not int or not 0 < input_size <= MAX_INPUT_BYTES
                or input_size > source.size):
            raise ValueError("Invalid recipe worker input size")
        # Drop the temporary view before close; pickle creates independent raw
        # bytes/operation objects. No mapping survives into native preparation.
        with source.buf[:input_size] as view:
            request = pickle.loads(view)
    finally:
        source.close()
    if type(request) is not dict or set(request) != {"raw", "operation"}:
        raise ValueError("Invalid recipe worker input envelope")
    _raw_bytes(request["raw"])
    return request["raw"], parse_operation(request["operation"])


def _download_result(result):
    if type(result) is not dict or type(result.get("issues")) is not list:
        raise ValueError("Invalid recipe recovery result")
    if "recovered_file" in result:
        raise ValueError("Recovery evaluator must not supply a pre-encoded file")
    if result.get("status") != "ready":
        if "candidate" in result:
            raise ValueError("Non-ready recovery result contains a candidate")
        return result
    candidate, recovery = result.get("candidate"), result.get("recovery")
    if (type(candidate) is not dict or type(recovery) is not dict
            or type(candidate.get("id")) is not str
            or candidate["id"] != recovery.get("recovered_design_id")):
        raise ValueError("Ready recovery result lacks its exact private copy identity")
    encoded = _result_bytes(candidate, limit=MAX_RESULT_BYTES, limit_result=_LIMIT_MARKER)
    if encoded == b'{"recovered_file_limit":true}':
        return failure("result_limit")
    # Shared JSONEncoder uses ensure_ascii=True. Preserve float/int spelling and
    # all original JSON escapes: the host serves these bytes without decoding a
    # Design or asking a browser to parse/stringify the document.
    artifact = {"json_text": encoded.decode("ascii"), "sha256": sha256(encoded).hexdigest(),
                "size_bytes": len(encoded)}
    return {**{key: value for key, value in result.items() if key != "candidate"},
            "recovered_file": artifact}


def _evaluate(input_name, input_size, output_name):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    output = SharedMemory(name=output_name)
    try:
        try:
            raw, operation = _read_request(input_name, input_size)
            result = _download_result(evaluate_file(raw, operation))
            encoded = _result_bytes(result, limit=MAX_RESULT_BYTES,
                                    limit_result=failure("result_limit"))
        except BaseException as exc:
            encoded = _result_bytes(failure("recovery_worker_error", exc), limit=MAX_RESULT_BYTES)
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        output.close()


class RecipeFileWorker(VerificationWorker):
    """Reuse process admission/reaping; this worker grants no publication right."""

    def __init__(self, raw, operation):
        _raw_bytes(raw)
        operation = parse_operation(operation)
        self._source_sha256 = sha256(raw).hexdigest()
        self._source_size = len(raw)
        self._operation_kind = operation["operation"]
        super().__init__({"raw": raw, "operation": operation}, _target=_evaluate,
                         _result_limit=MAX_RESULT_BYTES, _name="nadoc-recipe-file-recovery")

    def result(self):
        result = self._read_result()
        status = result.get("status")
        if status not in {"review", "ready", "failed", "unverified"} or "candidate" in result:
            raise ValueError("Invalid recipe file worker result")
        if ((status == "review" and self._operation_kind != "inspect")
                or (status == "ready" and self._operation_kind != "recover")):
            raise ValueError("Recipe result does not match its admitted operation")
        recovery = result.get("recovery")
        if recovery is not None:
            if (type(recovery) is not dict or recovery.get("source_sha256") != self._source_sha256
                    or type(recovery.get("source_size_bytes")) is not int
                    or recovery["source_size_bytes"] != self._source_size):
                raise ValueError("Recipe result does not match its original bytes")
        if status in {"review", "ready"} and recovery is None:
            raise ValueError("Recipe result has no original-file receipt")
        if status != "ready":
            if "recovered_file" in result:
                raise ValueError("Non-ready recipe result contains a downloadable file")
            return result
        artifact = result.get("recovered_file")
        if (type(artifact) is not dict or set(artifact) != {"json_text", "sha256", "size_bytes"}
                or type(artifact["json_text"]) is not str or not artifact["json_text"].isascii()
                or type(artifact["size_bytes"]) is not int
                or not 0 < artifact["size_bytes"] <= MAX_RESULT_BYTES
                or len(artifact["json_text"]) != artifact["size_bytes"]
                or type(artifact["sha256"]) is not str
                or sha256(artifact["json_text"].encode("ascii")).hexdigest() != artifact["sha256"]):
            raise ValueError("Recovered file does not match its exact byte receipt")
        return result

    def response_bytes(self):
        """Return checked child JSON verbatim, for the host's supervised send.

        VerificationWorker has already reaped the child before result access.
        This extra bounded raw copy avoids an event-loop JSON encode/Design
        parse. The host must retain admission until its response send finishes.
        """
        self.result()
        size = struct.unpack_from("!I", self._output.buf)[0]
        if not 0 < size <= self._result_limit:
            raise ValueError("Invalid recipe worker response size")
        return bytes(self._output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + size])
