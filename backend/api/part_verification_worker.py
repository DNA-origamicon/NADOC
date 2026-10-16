"""Disposable spawned proof worker with bounded, memory-only transport.

The pickle is produced exclusively from our admitted capture, never accepted
from an HTTP request or a saved file. It preserves unsupported legacy history
rows so proof can diagnose them without a schema migration. Results cross back
as bounded JSON. Shared buffers avoid a blocked pipe read hiding a deadline.
"""
from io import BytesIO
import json
import multiprocessing
from multiprocessing.connection import wait
from multiprocessing.shared_memory import SharedMemory
import os
import pickle
import struct
from time import monotonic


MAX_INPUT_BYTES = 2_000_000
MAX_RESULT_BYTES = 2_000_000
TERMINATE_GRACE_SECONDS = 0.5
KILL_POLL_SECONDS = 0.1
RESULT_HEADER_BYTES = 4


class WorkerLimit(ValueError):
    pass


class _BoundedInput(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_INPUT_BYTES:
            raise WorkerLimit("Part verification worker input budget exceeded")
        return super().write(data)


def failure(code, detail=None):
    issue = {"code": code}
    if detail is not None:
        issue["detail"] = str(detail)[:2048]
    return {"status": "unverified", "native_editable": False, "issues": [issue]}


def _result_bytes(result, *, limit=None, limit_result=None):
    limit = MAX_RESULT_BYTES if limit is None else limit
    chunks = []
    size = 0
    for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(result):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size > limit:
            if limit_result is not None:
                # A private framed caller can retain its input binding even
                # when output is refused. The fallback has the same byte cap.
                return _result_bytes(limit_result, limit=limit)
            return json.dumps(failure("result_limit")).encode("utf-8")
        chunks.append(encoded)
    return b"".join(chunks)


def _assess(input_name, input_size, result_name):
    # This child has no inherited document sessions. Bound native parallelism
    # before importing the model or command modules that may import NumPy/SciPy.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    output = SharedMemory(name=result_name)
    source = None
    try:
        try:
            source = SharedMemory(name=input_name)
            design = pickle.loads(source.buf[:input_size])
            from backend.api.part_proof_commands import dependencies, execute
            from backend.core.part_history_contract import assess_part_history

            result = assess_part_history(design, execute=execute, dependencies=dependencies)
            encoded = _result_bytes(result)
        except BaseException as exc:
            encoded = _result_bytes(failure("verification_error", exc))
        output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + len(encoded)] = encoded
        struct.pack_into("!I", output.buf, 0, len(encoded))
    finally:
        if source is not None:
            source.close()
        output.close()


class VerificationWorker:
    """One process, no pool or queue; the supervisor owns its whole lifetime."""

    def __init__(self, design, *, _target=_assess, _result_limit=None, _name="nadoc-part-proof"):
        stream = _BoundedInput()
        pickle.dump(design, stream, protocol=pickle.HIGHEST_PROTOCOL)
        payload = stream.getvalue()
        self._initialize_input((payload,), _target=_target, _result_limit=_result_limit, _name=_name)

    def _initialize_input(self, parts, *, _target, _result_limit, _name):
        """Allocate an already bounded private transport under supervisor ownership.

        Ordinary callers pass the unchanged bounded pickle. The strict byte
        worker supplies its separately checked full-document frame; no public
        input or user-selected size limit reaches this internal primitive.
        """
        size = sum(len(part) for part in parts)
        context = multiprocessing.get_context("spawn")
        self._result_limit = MAX_RESULT_BYTES if _result_limit is None else _result_limit
        self._buffers = []
        try:
            self._input = SharedMemory(create=True, size=size)
            self._buffers.append(self._input)
            offset = 0
            for part in parts:
                self._input.buf[offset:offset + len(part)] = part
                offset += len(part)
            self._output = SharedMemory(create=True, size=self._result_limit + RESULT_HEADER_BYTES)
            self._buffers.append(self._output)
            self._process = context.Process(
                target=_target,
                args=(self._input.name, size, self._output.name),
                name=_name,
                daemon=True,
            )
        except BaseException:
            self._release_buffers()
            raise
        self._process_closed = False
        self._closed = False

    def start(self):
        self._process.start()

    def wait(self, timeout):
        # No cross-process synchronization lock can be left held when a worker
        # is killed. Its exit sentinel publishes the completed shared buffer.
        deadline = monotonic() + max(0, timeout)
        while True:
            if not wait([self._process.sentinel], max(0, deadline - monotonic())):
                return False
            # EOF can become visible just before waitpid observes process exit.
            # Never read early; spend only this call's remaining polling budget
            # reaping the child so the supervisor keeps checking cancellation.
            self._process.join(timeout=min(0.01, max(0, deadline - monotonic())))
            if not self._process.is_alive():
                return True
            if monotonic() >= deadline:
                return False

    def is_alive(self):
        return not self._process_closed and self._process.is_alive()

    def _read_result(self):
        if self._process.is_alive():
            raise ValueError("Part verification worker has not exited")
        if self._process.exitcode != 0:
            return failure("worker_exited")
        size = struct.unpack_from("!I", self._output.buf)[0]
        if not 0 < size <= getattr(self, "_result_limit", MAX_RESULT_BYTES):
            raise ValueError("Invalid part verification worker result size")
        result = json.loads(bytes(self._output.buf[RESULT_HEADER_BYTES:RESULT_HEADER_BYTES + size]))
        if not isinstance(result, dict) or not isinstance(result.get("issues"), list):
            raise ValueError("Invalid part verification worker result")
        return result

    def result(self):
        result = self._read_result()
        if result.get("status") not in {"verified", "reproduced_import", "failed", "mismatch", "unverified"}:
            raise ValueError("Invalid part verification worker status")
        return result

    def _release_buffers(self):
        errors = []
        for buffer in self._buffers:
            try:
                buffer.close()
            except Exception as exc:
                errors.append(exc)
            try:
                buffer.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def close(self):
        if self._closed:
            return
        if not self._process_closed:
            process = self._process
            if process.pid is not None:
                if process.is_alive():
                    try:
                        process.terminate()
                    except OSError:
                        # Still try kill after the bounded graceful interval.
                        pass
                process.join(timeout=TERMINATE_GRACE_SECONDS)
                if process.is_alive():
                    process.kill()
                # An OS-level uninterruptible process may resist even kill.
                # Keep admission occupied until it is reaped instead of leaking
                # workers or claiming a hard OS guarantee we cannot provide.
                while process.is_alive():
                    process.join(timeout=KILL_POLL_SECONDS)
                process.join(timeout=0)
            try:
                process.close()
            except BaseException:
                # A reaped process handle can fail to close independently of
                # shared memory. Still attempt every buffer close and unlink.
                self._release_buffers()
                raise
            self._process_closed = True
        self._release_buffers()
        self._closed = True
