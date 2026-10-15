"""Bounded process transport for explicitly requested expensive recipe work.

The supervisor owns deadlines and publication. The child sees only a captured
authoring recipe and a server-validated operation, never a live document session.
"""

import json
import os
import pickle
import struct
from multiprocessing.shared_memory import SharedMemory

from backend.api.part_verification_worker import (
    RESULT_HEADER_BYTES, VerificationWorker, _result_bytes, failure,
)
from backend.core.part_operation_input import validate_operation_input


MAX_CANDIDATE_BYTES = 16_000_000


def _evaluate(input_name, input_size, output_name):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    output = SharedMemory(name=output_name)
    source = None
    try:
        try:
            source = SharedMemory(name=input_name)
            request = pickle.loads(source.buf[:input_size])
            from backend.api.part_evaluation import evaluate

            result = evaluate(**request)
        except BaseException as exc:
            result = failure("evaluation_error", exc)
        encoded = _result_bytes(result, limit=MAX_CANDIDATE_BYTES)
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        if source is not None:
            source.close()
        output.close()


class EvaluationWorker(VerificationWorker):
    def __init__(self, design, operation):
        # A strict JSON request cannot supply Python objects to the trusted
        # internal pickle transport. Its combined size is bounded before spawn.
        validate_operation_input(operation)
        operation = json.loads(json.dumps(operation, allow_nan=False))
        super().__init__({"source": design, "operation": operation},
                         _target=_evaluate, _result_limit=MAX_CANDIDATE_BYTES,
                         _name="nadoc-part-evaluation")

    def result(self):
        result = self._read_result()
        if result.get("status") not in {
            "ready", "preview", "verified", "reproduced_import", "failed", "mismatch", "unverified",
        }:
            raise ValueError("Invalid part evaluation result")
        if result["status"] == "ready" and not isinstance(result.get("candidate"), dict):
            raise ValueError("Part evaluation candidate is missing")
        return result
