"""Process isolation and bounded transport, without molecular solver work."""
import json
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
import struct
from threading import Event
from types import SimpleNamespace

import pytest

from backend.api import part_verification_worker as workers
from backend.core.part_history_contract import create_empty_part


def _block_until_terminated(connection):
    connection.send_bytes(b"ready")
    connection.close()
    Event().wait()


def _assert_unlinked(names):
    for name in names:
        try:
            unexpected = SharedMemory(name=name)
        except FileNotFoundError:
            continue
        try:
            pytest.fail(f"Worker shared memory {name} was not unlinked")
        finally:
            unexpected.close()
            unexpected.unlink()


def test_worker_input_is_bounded_before_process_creation(monkeypatch):
    monkeypatch.setattr(workers, "MAX_INPUT_BYTES", 128)
    with pytest.raises(workers.WorkerLimit, match="input budget"):
        workers.VerificationWorker(create_empty_part("x" * 1000, "SQUARE"))


def test_oversized_result_becomes_nonverified_diagnostic(monkeypatch):
    monkeypatch.setattr(workers, "MAX_RESULT_BYTES", 256)
    encoded = workers._result_bytes({"status": "verified", "issues": [], "extra": "x" * 1000})
    assert len(encoded) <= 256
    assert json.loads(encoded) == workers.failure("result_limit")


def test_worker_rejects_invalid_result_size():
    worker = object.__new__(workers.VerificationWorker)
    worker._process = SimpleNamespace(is_alive=lambda: False, exitcode=0)
    worker._output = SimpleNamespace(buf=struct.pack("!I", workers.MAX_RESULT_BYTES + 1))
    with pytest.raises(ValueError, match="result size"):
        worker.result()


def test_cleanup_escalates_to_kill_and_reaps_before_close():
    actions = []

    class ResistantProcess:
        pid = 123
        alive = True

        def is_alive(self):
            return self.alive

        def terminate(self):
            actions.append("terminate")

        def kill(self):
            actions.append("kill")

        def join(self, timeout):
            actions.append("join")
            if "kill" in actions:
                self.alive = False

        def close(self):
            assert not self.alive
            actions.append("close")

    worker = object.__new__(workers.VerificationWorker)
    worker._process = ResistantProcess()
    worker._process_closed = False
    worker._buffers = []
    worker._closed = False
    worker.close()
    assert actions[:3] == ["terminate", "join", "kill"]
    assert actions[-2:] == ["join", "close"]


def test_exit_sentinel_does_not_publish_before_process_is_reaped(monkeypatch):
    alive = iter([True, False])
    joined = []
    worker = object.__new__(workers.VerificationWorker)
    worker._process = SimpleNamespace(
        sentinel=123,
        join=lambda timeout: joined.append(timeout),
        is_alive=lambda: next(alive),
    )
    monkeypatch.setattr(workers, "wait", lambda handles, timeout: handles)
    assert worker.wait(0.1)
    assert len(joined) == 2
    assert all(0 <= timeout <= 0.01 for timeout in joined)


def test_zero_timeout_does_not_wait_for_exit_race(monkeypatch):
    joined = []
    worker = object.__new__(workers.VerificationWorker)
    worker._process = SimpleNamespace(
        sentinel=123,
        join=lambda timeout: joined.append(timeout),
        is_alive=lambda: True,
    )
    monkeypatch.setattr(workers, "wait", lambda handles, timeout: handles)
    assert not worker.wait(0)
    assert joined == [0]


def test_allocation_failure_unlinks_previously_allocated_memory(monkeypatch):
    allocated = []

    def allocate(**kwargs):
        if allocated:
            raise OSError("Injected shared-memory allocation failure")
        buffer = SharedMemory(**kwargs)
        allocated.append(buffer.name)
        return buffer

    monkeypatch.setattr(workers, "SharedMemory", allocate)
    try:
        with pytest.raises(OSError, match="allocation failure"):
            workers.VerificationWorker(create_empty_part("Allocation", "SQUARE"))
    finally:
        _assert_unlinked(allocated)


def test_buffer_cleanup_attempts_every_unlink_after_close_failure():
    actions = []

    def failed_close():
        actions.append("first-close")
        raise BufferError("Injected outstanding view")

    worker = object.__new__(workers.VerificationWorker)
    worker._buffers = [
        SimpleNamespace(close=failed_close, unlink=lambda: actions.append("first-unlink")),
        SimpleNamespace(close=lambda: actions.append("second-close"),
                        unlink=lambda: actions.append("second-unlink")),
    ]
    with pytest.raises(BufferError):
        worker._release_buffers()
    assert actions == ["first-close", "first-unlink", "second-close", "second-unlink"]


def test_reaped_process_handle_failure_still_unlinks_buffers(monkeypatch):
    worker = workers.VerificationWorker(create_empty_part("Close failure", "SQUARE"))
    names = [buffer.name for buffer in worker._buffers]
    close = worker._process.close

    def fail_close():
        raise OSError("Injected process handle close failure")

    monkeypatch.setattr(worker._process, "close", fail_close)
    try:
        with pytest.raises(OSError, match="handle close"):
            worker.close()
        _assert_unlinked(names)
    finally:
        monkeypatch.setattr(worker._process, "close", close)
        worker.close()


@pytest.mark.parametrize("failures", [1, 5])
def test_supervisor_retries_buffer_unlink_after_child_is_reaped(monkeypatch, failures):
    from backend.api.part_verification_jobs import _dispose

    worker = workers.VerificationWorker(create_empty_part("Unlink retry", "SQUARE"))
    names = [buffer.name for buffer in worker._buffers]
    unlink = SharedMemory.unlink
    failed = 0

    def fail_unlink(buffer):
        nonlocal failed
        if buffer.name == names[0] and failed < failures:
            failed += 1
            raise OSError("Injected repeated unlink failure")
        return unlink(buffer)

    monkeypatch.setattr(SharedMemory, "unlink", fail_unlink)
    job = SimpleNamespace(revision=1, result=None, status="running")
    try:
        problem = _dispose(job, worker, "source")
        assert problem["issues"][0]["code"] == "worker_cleanup_error"
        assert failed == failures and worker._closed
        _assert_unlinked(names)
    finally:
        worker.close()


def test_spawned_worker_reproduces_empty_part_and_is_reaped():
    # Uses the production spawn entry point, imports and serialized projection.
    # No disk scratch, live session, command solver or model fixture is needed.
    worker = workers.VerificationWorker(create_empty_part("Spawned", "SQUARE"))
    process = worker._process
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(10), "Spawned verification did not produce a result"
        result = worker.result()
        assert result["status"] == "verified"
        assert result["native_editable"] is True
        assert result["checked_commands"] == 0
    finally:
        worker.close()
        _assert_unlinked(names)
    assert process._closed


def test_spawned_blocked_worker_is_terminated_without_cooperation():
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    worker = object.__new__(workers.VerificationWorker)
    worker._closed = False
    worker._process_closed = False
    worker._buffers = []
    worker._process = context.Process(target=_block_until_terminated, args=(writer,), daemon=True)
    process = worker._process
    try:
        worker.start()
        writer.close()
        assert reader.poll(5), "Blocking worker failed to start"
        assert reader.recv_bytes() == b"ready"
        assert worker.is_alive()
    finally:
        worker.close()
        reader.close()
        writer.close()
    assert process._closed
    assert not worker.is_alive()
