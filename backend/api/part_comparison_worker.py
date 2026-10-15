"""One bounded, disposable display worker; no job catalog or publication path."""

import os
import pickle
import struct
from multiprocessing.shared_memory import SharedMemory

from backend.api.part_verification_worker import (
    RESULT_HEADER_BYTES, VerificationWorker, _result_bytes, failure,
)


def _project(input_name, input_size, output_name):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    output, source = SharedMemory(name=output_name), None
    try:
        try:
            source = SharedMemory(name=input_name)
            value = pickle.loads(source.buf[:input_size])
            from backend.core.part_command_errors import CommandContractError
            from backend.core.part_comparison_projection import compare
            from threadpoolctl import threadpool_limits

            try:
                with threadpool_limits(limits=1):
                    result = compare(value["source"], value["candidate"])
            except CommandContractError as error:
                result = {"status": "unverified", "issues": [error.as_issue()]}
            encoded = _result_bytes(result)
        except BaseException as error:
            encoded = _result_bytes(failure("comparison_error", error))
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        if source is not None:
            source.close()
        output.close()


class ComparisonWorker(VerificationWorker):
    """The unchanged 2 MB input/result transport applies to both panes together."""

    def __init__(self, source, candidate):
        super().__init__({"source": source, "candidate": candidate},
                         _target=_project, _name="nadoc-part-comparison")

    def result(self):
        result = self._read_result()
        if result.get("status") not in {"projected", "unverified"}:
            raise ValueError("Invalid part comparison result")
        if result["status"] == "projected" and not all(isinstance(result.get(key), dict) for key in (
                "published", "proposed", "coverage", "candidate_digests")):
            raise ValueError("Incomplete part comparison projection")
        return result
