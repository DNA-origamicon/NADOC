"""Real process/FD ownership regressions; no simulation engine is launched."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from backend.core import simulation_runtime as runtime


_ROOT = Path(__file__).resolve().parents[1]
_OWNER = """
import json, sys
from pathlib import Path
from backend.core import simulation_runtime as runtime
directory = Path(sys.argv[1])
lease = runtime.claim(directory)
print(json.dumps({'claimed': lease is not None, 'generation': lease.generation}), flush=True)
try:
    for line in sys.stdin:
        command = json.loads(line)
        if command['op'] == 'exit':
            break
        if command['op'] == 'status':
            result = {'stop': lease.stop_requested(), 'control': runtime.read_control(
                directory, 'early_stop', consume=command.get('consume', False))}
        elif command['op'] == 'identify':
            lease.identify(command['kind'])
            result = {'ok': True}
        print(json.dumps(result), flush=True)
finally:
    lease.close()
"""


def _reply(process):
    ready, _, _ = select.select([process.stdout], [], [], 5)
    assert ready, "Runtime fixture did not answer within five seconds"
    line = process.stdout.readline()
    assert line, f"Runtime fixture exited unexpectedly: {process.poll()}"
    return json.loads(line)


def _command(process, operation, **values):
    process.stdin.write(json.dumps({"op": operation, **values}) + "\n")
    process.stdin.flush()
    return _reply(process)


@contextmanager
def _owner(directory):
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _OWNER, str(directory)], cwd=_ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready = _reply(process)
        assert ready["claimed"]
        yield process, ready["generation"]
    finally:
        if process.poll() is None:
            process.stdin.write('{"op":"exit"}\n')
            process.stdin.flush()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def _wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "Runtime fixture did not reach the expected state"
        time.sleep(.01)


def test_real_owner_death_releases_lock_without_replacing_its_inode(tmp_path):
    directory = tmp_path / "job"
    assert not runtime.is_owned(directory)
    assert not directory.exists()  # Read-only polling must not invent a job.
    with _owner(directory) as (process, generation):
        inode = (directory / ".runtime.lock").stat().st_ino
        (directory / "job.json").write_text('{"status":"stopped","pid":1}')
        assert runtime.known(directory)
        assert runtime.is_owned(directory)  # Stale status/PID is not ownership.
        assert runtime.claim(directory) is None
        process.kill()
        process.wait(timeout=5)
        assert not runtime.is_owned(directory)
        replacement = runtime.claim(directory)
        try:
            assert replacement is not None
            assert replacement.generation != generation
            assert (directory / ".runtime.lock").stat().st_ino == inode
        finally:
            replacement.close()


def test_stop_and_controls_are_scoped_to_the_live_execution_generation(tmp_path):
    with _owner(tmp_path) as (process, generation):
        assert runtime.request_stop(tmp_path)
        assert runtime.set_control(tmp_path, "early_stop", True)
        assert _command(process, "status", consume=True) == {"stop": True, "control": True}
        assert _command(process, "status")["control"] is None
        assert runtime.set_control(tmp_path, "early_stop", False)
        assert _command(process, "status", consume=True)["control"] is False
        assert _command(process, "status")["control"] is None
        assert runtime.set_control(tmp_path, "early_stop", True)  # Deliberately unconsumed.
    assert not runtime.request_stop(tmp_path)
    assert not runtime.set_control(tmp_path, "early_stop", False)
    with _owner(tmp_path) as (process, next_generation):
        assert next_generation != generation
        assert _command(process, "status", consume=True) == {"stop": False, "control": None}


def test_detached_pid_requires_worker_identity_and_matching_process_birth(tmp_path):
    with _owner(tmp_path) as (process, _generation):
        assert runtime.worker_pid(tmp_path) is None  # Launcher/thread PID is never a kill target.
        _command(process, "identify", kind="worker")
        assert runtime.worker_pid(tmp_path) == process.pid
        state_path = tmp_path / ".runtime.json"
        state = json.loads(state_path.read_text())
        state["birth"] = "stale-recycled-pid"
        state_path.write_text(json.dumps(state))
        assert runtime.worker_pid(tmp_path) is None
    assert runtime.worker_pid(tmp_path) is None


def test_thread_exception_releases_ownership_after_registry_removal(tmp_path, monkeypatch):
    registry, errors = {}, []
    entered, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(threading, "excepthook", errors.append)

    def target():
        registry.pop("job")
        entered.set()
        assert finish.wait(5)
        raise RuntimeError("fixture failure after registry cleanup")

    # Keep the actual thread separately because runners may pop their registry
    # before completing final output publication.
    handles = []

    def handle_type(**values):
        handle = SimpleNamespace(**values)
        handles.append(handle)
        return handle

    assert runtime.launch_thread(tmp_path, "job", target, registry, handle_type,
                                 lambda: None, name="runtime-test")
    try:
        assert entered.wait(5)
        assert not registry
        assert runtime.is_owned(tmp_path)
        assert runtime.claim(tmp_path) is None
    finally:
        finish.set()
        handles[0].thread.join(5)
    assert not handles[0].thread.is_alive()
    assert not runtime.is_owned(tmp_path)
    assert len(errors) == 1
    assert isinstance(errors[0].exc_value, RuntimeError)


def test_thread_preparation_failure_releases_the_claim(tmp_path):
    registry = {}

    def fail():
        raise ValueError("fixture preparation failure")

    with pytest.raises(ValueError, match="preparation failure"):
        runtime.launch_thread(tmp_path, "job", lambda: None, registry, SimpleNamespace,
                              lambda: None, name="runtime-test", before_start=fail)
    assert not registry
    assert not runtime.is_owned(tmp_path)


def test_other_process_owner_blocks_thread_launch_before_state_changes(tmp_path):
    registry, changed = {}, []
    with _owner(tmp_path):
        assert not runtime.launch_thread(
            tmp_path, "job", lambda: changed.append("ran"), registry, SimpleNamespace,
            lambda: None, name="runtime-test", before_start=lambda: changed.append("prepared"),
        )
        assert not changed
        assert not registry


def test_stop_from_another_process_reaches_the_owning_thread(tmp_path):
    registry = {}
    entered, stop = threading.Event(), threading.Event()

    def target():
        entered.set()
        assert stop.wait(5)

    assert runtime.launch_thread(tmp_path, "job", target, registry, SimpleNamespace,
                                 stop.set, name="runtime-test")
    try:
        assert entered.wait(5)
        result = subprocess.run(
            [sys.executable, "-c", "from backend.core.simulation_runtime import request_stop; "
             "import sys; print(request_stop(sys.argv[1]))", str(tmp_path)],
            cwd=_ROOT, check=True, capture_output=True, text=True, timeout=5,
        )
        assert result.stdout.strip() == "True"
        assert stop.wait(5)
    finally:
        stop.set()
        registry["job"].thread.join(5)
    assert not registry["job"].thread.is_alive()
    assert not runtime.is_owned(tmp_path)


def test_stop_is_retried_until_the_initializing_runner_can_accept_it(tmp_path):
    registry, attempts = {}, []
    entered, ready, ignored, stopped = (threading.Event() for _ in range(4))

    def target():
        entered.set()
        assert ready.wait(5)
        assert stopped.wait(5)

    def on_stop():
        attempts.append(ready.is_set())
        if ready.is_set():
            stopped.set()
        else:
            ignored.set()

    assert runtime.launch_thread(tmp_path, "job", target, registry, SimpleNamespace,
                                 on_stop, name="runtime-test")
    try:
        assert entered.wait(5)
        assert runtime.request_stop(tmp_path)
        assert ignored.wait(5)  # Cancellation arrived before the task existed.
        assert runtime.is_owned(tmp_path)
        assert not stopped.is_set()
        ready.set()
        assert stopped.wait(5)  # The durable request must be delivered again.
    finally:
        ready.set()
        stopped.set()
        registry["job"].thread.join(5)
    assert attempts[0] is False
    assert True in attempts
    assert not registry["job"].thread.is_alive()
    assert not runtime.is_owned(tmp_path)


def test_stop_watcher_start_failure_releases_the_execution_lease(tmp_path, monkeypatch):
    lease = runtime.claim(tmp_path)
    ran = []

    def fail_start(_thread):
        raise RuntimeError("fixture watcher start failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError, match="watcher start failure"):
        lease.thread_target(lambda: ran.append(True), lambda: None)()
    assert not ran
    assert lease.fd == -1
    assert not runtime.is_owned(tmp_path)


@pytest.fixture
def detached_fixture(tmp_path, monkeypatch):
    """An actual `python -m` worker adopting the inherited FD and publication gate."""
    monkeypatch.setenv("PYTHONPATH", str(_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    module = tmp_path / "runtime_fixture_worker.py"
    module.write_text('''
import json, os, sys, time
from pathlib import Path
from backend.core.simulation_runtime import worker_lease
directory = Path(sys.argv[1]) / sys.argv[2]
gate_fd = int(os.environ['NADOC_SIMULATION_READY_FD'])
native_read = os.read
def observed_read(fd, count):
    if fd == gate_fd:
        (directory / "waiting_at_gate").touch()
    return native_read(fd, count)
os.read = observed_read
with worker_lease(directory) as lease:
    os.read = native_read
    if lease is None:
        raise RuntimeError("No lease inherited")
    manifest = json.loads((directory / "job.json").read_text())
    if lease.stop_requested():
        manifest["status"] = "stopped"
        (directory / "job.json").write_text(json.dumps(manifest))
        sys.exit(0)
    temporary = directory / "entered.tmp"
    temporary.write_text(json.dumps(manifest))
    temporary.replace(directory / "entered.json")
    deadline = time.monotonic() + 5
    while not (directory / "release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Fixture was not released")
        time.sleep(.01)
    manifest["status"] = "completed"
    (directory / "job.json").write_text(json.dumps(manifest))
''')

    class Job:
        job_id = "job"
        pid = None
        status = "queued"
        stages = []

        def job_dir(self, workspace):
            return Path(workspace) / self.job_id

        def save(self, workspace):
            (self.job_dir(workspace) / "job.json").write_text(json.dumps({
                "pid": self.pid, "status": self.status,
            }))

    return Job(), module.stem


def test_detached_worker_keeps_the_inherited_lock_after_parent_closes_its_fd(tmp_path, detached_fixture):
    job, module = detached_fixture
    directory = job.job_dir(tmp_path)
    reaped = threading.Event()

    def before_gate(process):
        _wait_until(lambda: (directory / "waiting_at_gate").exists())
        assert process.poll() is None
        assert runtime.worker_pid(directory) is None
        assert not (directory / "entered.json").exists()

    process = runtime.launch_detached(job, tmp_path, module, tmp_path,
                                      on_spawn=before_gate, on_exit=reaped.set)
    try:
        _wait_until(lambda: (directory / "entered.json").exists())
        assert json.loads((directory / "entered.json").read_text()) == {
            "pid": process.pid, "status": "running",
        }
        assert runtime.worker_pid(directory) == process.pid
        assert runtime.is_owned(directory)
        assert runtime.launch_detached(job, tmp_path, module, tmp_path) is None
    finally:
        (directory / "release").touch()
        process.wait(timeout=5)
    assert reaped.wait(5)
    assert process.returncode == 0
    assert not runtime.is_owned(directory)
    assert json.loads((directory / "job.json").read_text())["status"] == "completed"


def test_stop_during_detached_handoff_reaches_worker_after_manifest_publication(tmp_path, detached_fixture):
    job, module = detached_fixture
    directory = job.job_dir(tmp_path)
    reaped = threading.Event()

    def before_gate(_process):
        _wait_until(lambda: (directory / "waiting_at_gate").exists())
        assert runtime.worker_pid(directory) is None
        assert runtime.request_stop(directory)
        assert not (directory / "entered.json").exists()

    process = runtime.launch_detached(job, tmp_path, module, tmp_path,
                                      on_spawn=before_gate, on_exit=reaped.set)
    try:
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert reaped.wait(5)
    assert process.returncode == 0
    assert not runtime.is_owned(directory)
    assert not (directory / "entered.json").exists()
    assert json.loads((directory / "job.json").read_text())["status"] == "stopped"


def test_detached_worker_cannot_run_after_manifest_publication_fails(tmp_path, detached_fixture):
    job, module = detached_fixture
    directory = job.job_dir(tmp_path)
    reaped = threading.Event()

    def fail_save(_workspace):
        raise OSError("fixture disk failure")

    job.save = fail_save
    with pytest.raises(OSError, match="disk failure"):
        runtime.launch_detached(job, tmp_path, module, tmp_path, on_exit=reaped.set)
    assert reaped.wait(5)
    assert not runtime.is_owned(directory)
    assert not (directory / "entered.json").exists()
    assert "before publishing the job" in (directory / "worker.log").read_text()


def test_detached_pipe_creation_failure_releases_the_claim(tmp_path, detached_fixture, monkeypatch):
    job, module = detached_fixture

    def fail_pipe():
        raise OSError("fixture pipe failure")

    monkeypatch.setattr(runtime.os, "pipe", fail_pipe)
    with pytest.raises(OSError, match="pipe failure"):
        runtime.launch_detached(job, tmp_path, module, tmp_path)
    assert not runtime.is_owned(job.job_dir(tmp_path))
    replacement = runtime.claim(job.job_dir(tmp_path))
    assert replacement is not None
    replacement.close()
