"""Same-host ownership for managed simulations, independent of the caller process.

A kernel file lock covers runner preparation, engine execution, inter-stage work and
result publication. Unlike a process-local thread registry or a child PID, it
cannot lose a living headless runner during UI polling, survive its owner's
death, or mistake a recycled PID for a new worker. The lock file is never
unlinked: replacing its inode would create two independent owners.

Stop requests are generation-scoped messages. Thread runners consume them by
calling their ordinary in-process stop handler; polling processes do not rewrite
the owner's job.json. Detached workers inherit the same lock across Popen.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import MutableMapping
from dataclasses import dataclass
from functools import wraps
import inspect
import fcntl
import json
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

_LOCK = '.runtime.lock'
_STATE = '.runtime.json'
_STOP = '.runtime-stop.json'
_FD_ENV = 'NADOC_SIMULATION_OWNER_FD'
_READY_ENV = 'NADOC_SIMULATION_READY_FD'
_WORKSPACE = ContextVar('simulation_workspace', default=None)
_RESERVATION = ContextVar('simulation_reservation', default=None)
_LOG = logging.getLogger(__name__)


def workspace(default):
    """Request/context-local override used by headless calls to the real routes."""
    return _WORKSPACE.get() or Path(default)


@contextmanager
def use_workspace(path):
    token = _WORKSPACE.set(Path(path))
    try:
        yield
    finally:
        _WORKSPACE.reset(token)


class Registry(MutableMapping):
    """Locked, workspace-scoped handles; bare-ID inspection remains compatible.

    Native calls and runner threads bind their explicit workspace. Legacy callers
    without a workspace may inspect a unique job ID, but never choose among two
    workspaces containing the same copied ID.
    """
    def __init__(self):
        self._data = {}
        self._lock = threading.RLock()

    def _key(self, key):
        scope = _WORKSPACE.get()
        scoped = (str(Path(scope).resolve()) if scope is not None else None, key)
        if scoped in self._data:
            return scoped
        if (None, key) in self._data:  # legacy injected/local handle
            return (None, key)
        if scope is None:
            matches = [candidate for candidate in self._data if candidate[1] == key]
            if len(matches) == 1:
                return matches[0]
        return scoped

    def __getitem__(self, key):
        with self._lock:
            return self._data[self._key(key)]

    def __setitem__(self, key, value):
        with self._lock:
            scope = _WORKSPACE.get()
            self._data[(str(Path(scope).resolve()) if scope is not None else None, key)] = value

    def __delitem__(self, key):
        with self._lock:
            del self._data[self._key(key)]

    def __iter__(self):
        with self._lock:
            return iter([key[1] for key in self._data])

    def __len__(self):
        with self._lock:
            return len(self._data)

    def pop(self, key, *default):
        with self._lock:
            return self._data.pop(self._key(key), *default)

    def values(self):
        # GPU protection needs every process, including copied IDs in other workspaces.
        with self._lock:
            return list(self._data.values())

    def clear(self):
        with self._lock:
            self._data.clear()


def in_workspace(function):
    """Bind explicit native-call workspace for local registries and nested calls."""
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        with use_workspace(bound.arguments['workspace_dir']):
            return function(*args, **kwargs)
    return wrapped


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path, value):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _birth(pid):
    try:
        # comm may contain spaces or parentheses; field 22 is starttime.
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def known(job_dir):
    reservation = _reservation(job_dir)
    if reservation is not None:
        return reservation.previous_state is not None
    return (Path(job_dir) / _STATE).exists()


def is_owned(job_dir):
    """Probe without creating files or interpreting persisted status/PIDs."""
    if _reservation(job_dir) is not None:
        return False
    try:
        fd = os.open(Path(job_dir) / _LOCK, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


def owned_job(folder, job_id, workspace_dir=None):
    return is_owned(job_path(folder, job_id, workspace_dir))


def job_path(folder, job_id, workspace_dir=None):
    default = Path(os.environ.get('NADOC_WORKSPACE', Path(__file__).resolve().parents[2] / 'workspace'))
    return (Path(workspace_dir) if workspace_dir is not None else workspace(default)) / folder / job_id


def request_stop(job_dir):
    job_dir = Path(job_dir)
    if not is_owned(job_dir):
        return False
    generation = _read(job_dir / _STATE).get('generation')
    if generation:
        _write(job_dir / _STOP, {'generation': generation})
        return True
    return False


def set_control(job_dir, name, value):
    directory = Path(job_dir)
    generation = _read(directory / _STATE).get('generation')
    if generation and is_owned(directory):
        _write(directory / ('.runtime-control-' + name + '.json'),
               {'generation': generation, 'command': uuid.uuid4().hex, 'value': value})
        return True
    return False


def read_control(job_dir, name, *, consume=False):
    directory = Path(job_dir)
    if not is_owned(directory):
        return None
    path = directory / ('.runtime-control-' + name + '.json')
    value = _read(path)
    if value.get('generation') != _read(directory / _STATE).get('generation'):
        return None
    ack = directory / ('.runtime-control-' + name + '-ack.json')
    if not value.get('command') or _read(ack).get('command') == value['command']:
        return None
    if consume:
        # Acknowledge this command, without deleting a concurrently newer one.
        _write(ack, {'command': value['command']})
    return value.get('value')


@dataclass
class Lease:
    directory: Path
    fd: int
    generation: str

    def identify(self, kind='thread'):
        _write(self.directory / _STATE, dict(generation=self.generation, pid=os.getpid(),
               birth=_birth(os.getpid()), kind=kind, started_at=time.time()))

    def stop_requested(self):
        return _read(self.directory / _STOP).get('generation') == self.generation

    def close(self):
        if self.fd >= 0:
            # Do not LOCK_UN: a detached worker may share this open description.
            os.close(self.fd)
            self.fd = -1

    def thread_target(self, target, on_stop):
        """Own the entire target, including finalization after its registry pops."""
        def run():
            done = threading.Event()

            def watch():
                while not done.wait(.1):
                    if self.stop_requested():
                        try:
                            with use_workspace(self.directory.parent.parent):
                                on_stop()
                        except Exception:
                            _LOG.exception('Could not stop simulation owner %s', self.directory)
                        # A runner can still be initializing its event loop/task.
                        # Keep the durable request active until execution exits.

            watcher = threading.Thread(target=watch, name='simulation-stop', daemon=True)
            try:
                watcher.start()
                with use_workspace(self.directory.parent.parent):
                    target()
            finally:
                done.set()
                if watcher.ident is not None:
                    watcher.join()
                self.close()
        return run


def claim(job_dir, *, publish=True):
    """Atomically claim a new execution generation; None means already owned."""
    directory = Path(job_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / _LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    lease = Lease(directory, fd, uuid.uuid4().hex)
    try:
        if publish:
            lease.identify()
    except BaseException:
        lease.close()
        raise
    return lease


@dataclass
class _Reservation:
    lease: Lease
    previous_state: bytes | None
    transferred: bool = False


def _reservation(job_dir):
    value = _RESERVATION.get()
    if value is not None and not value.transferred and value.lease.directory.resolve() == Path(job_dir).resolve():
        return value
    return None


def _take_claim(job_dir):
    reservation = _reservation(job_dir)
    if reservation is not None:
        reservation.transferred = True
        return reservation.lease
    return claim(job_dir)


@contextmanager
def _reserve(job_dir, *, publish):
    """Reserve status writes before handing the same lock to a runner."""
    directory = Path(job_dir)
    # Reconciliation called inside a start request shares its existing lock.
    if _reservation(directory) is not None:
        yield True
        return
    lease = claim(directory, publish=False)
    if lease is None:
        yield False
        return
    state = directory / _STATE
    try:
        previous = state.read_bytes() if state.exists() else None
    except BaseException:
        lease.close()
        raise
    reservation = _Reservation(lease, previous)
    token = _RESERVATION.set(reservation)
    try:
        if publish:
            lease.identify()
        yield True
    finally:
        _RESERVATION.reset(token)
        if not reservation.transferred:
            try:
                if publish:
                    if previous is None:
                        state.unlink(missing_ok=True)
                    else:
                        _write(state, json.loads(previous))
            finally:
                lease.close()


def generation(job_dir):
    return _read(Path(job_dir) / _STATE).get('generation')


@contextmanager
def idle_stop_update(job_dir, expected_generation):
    """Publish an old stop only while idle and still on that execution attempt."""
    with _reserve(job_dir, publish=False) as acquired:
        yield acquired and generation(job_dir) == expected_generation


def idle_stop_guard(folder):
    """Serialize orphan cancellation/status writes with concurrent start/resume."""
    def decorate(function):
        @wraps(function)
        def wrapped(job_id, workspace_dir):
            with use_workspace(workspace_dir):
                directory = job_path(folder, job_id, workspace_dir)
                if not directory.exists() or is_owned(directory):
                    return function(job_id, workspace_dir)
                observed = generation(directory)
                with idle_stop_update(directory, observed) as acquired:
                    if not acquired:
                        return False  # a newer start owns its own manifest
                    return function(job_id, workspace_dir)
        return wrapped
    return decorate


def start_request(workspace_fn, folder, *, busy_message=None):
    """Serialize an API start/resume's status edits with native runner ownership.

    The native launcher consumes the reservation. Rejected requests restore the
    prior owner metadata (including legacy PID-only jobs) and release the lock.
    """
    def decorate(function):
        @wraps(function)
        async def wrapped(job_id, *args, **kwargs):
            with use_workspace(workspace_fn()):
                with _reserve(job_path(folder, job_id), publish=True) as acquired:
                    if not acquired:
                        if busy_message is not None:
                            from fastapi import HTTPException
                            raise HTTPException(400, busy_message)
                        return {'ok': True, 'message': 'Job already running'}
                    return await function(job_id, *args, **kwargs)
        # FastAPI must resolve forward annotations in the original module.
        wrapped.__signature__ = inspect.signature(function, eval_str=True)
        return wrapped
    return decorate


def reconcile_guard(function=None, *, read_only=None):
    """Keep orphan recovery atomic with respect to a concurrent start request.

    Native no-op states may opt out before a legacy job has an execution lease;
    read-only previews must not create lifecycle files just by inspecting them.
    """
    if function is None:
        return lambda target: reconcile_guard(target, read_only=read_only)
    @wraps(function)
    def wrapped(job, workspace_dir, *args, **kwargs):
        with use_workspace(workspace_dir):
            if read_only is not None and read_only(job) and not known(job.job_dir(workspace_dir)):
                return function(job, workspace_dir, *args, **kwargs)
            if not job.job_dir(workspace_dir).exists():
                # Archived/terminal reads must not recreate a removed job directory.
                return function(job, workspace_dir, *args, **kwargs)
            with _reserve(job.job_dir(workspace_dir), publish=False) as acquired:
                if not acquired:
                    return job
                if known(job.job_dir(workspace_dir)) and (job.job_dir(workspace_dir) / 'job.json').is_file():
                    # The caller loaded before acquiring the lease; an owner may
                    # have published its final fields in that interval. Preserve
                    # object identity for callers while refreshing managed jobs.
                    fresh = type(job).load(job.job_id, workspace_dir)
                    job.__dict__.update(fresh.__dict__)
                return function(job, workspace_dir, *args, **kwargs)
    return wrapped



def launch_thread(job_dir, job_id, target, registry, handle_type, on_stop, *, name, before_start=None):
    """Claim before touching job state or the local registry; release on failure."""
    lease = _take_claim(job_dir)
    if lease is None:
        return False
    try:
        if before_start is not None:
            before_start()
        thread = threading.Thread(target=lease.thread_target(target, on_stop), name=name, daemon=True)
        with use_workspace(Path(job_dir).parent.parent):
            registry[job_id] = handle_type(thread=thread)
            thread.start()
    except BaseException:
        with use_workspace(Path(job_dir).parent.parent):
            registry.pop(job_id, None)
        lease.close()
        raise
    return True


def worker_pid(job_dir):
    """Verified detached owner only; never return the launcher/server PID."""
    if not is_owned(job_dir):
        return None
    state = _read(Path(job_dir) / _STATE)
    pid = state.get('pid')
    if state.get('kind') == 'worker' and pid and state.get('birth') and state['birth'] == _birth(pid):
        return pid
    return None


@contextmanager
def worker_lease(job_dir):
    """Adopt Popen's lease, waiting until the parent publishes the job manifest."""
    fd = os.environ.pop(_FD_ENV, None)
    ready = os.environ.pop(_READY_ENV, None)
    descriptor = int(fd) if fd is not None else None
    gate = int(ready) if ready is not None else None
    lease = None
    try:
        if descriptor is None:
            lease = claim(job_dir)
        else:
            directory = Path(job_dir)
            expected = (directory / _LOCK).stat()
            actual = os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise RuntimeError('Simulation lease does not match this job')
            lease = Lease(directory, descriptor, _read(directory / _STATE)['generation'])
            descriptor = None  # lease now owns cleanup
        if gate is not None:
            if os.read(gate, 1) != b'1':
                raise RuntimeError('Simulation launcher exited before publishing the job')
        # Before publication stops are mailbox-only: never kill a child while
        # its parent can still overwrite its stopped manifest with running.
        if lease is not None:
            lease.identify('worker')
        yield lease
    finally:
        if gate is not None:
            os.close(gate)
        if descriptor is not None:
            os.close(descriptor)
        if lease is not None:
            lease.close()


def launch_detached(job, workspace_dir, module, repo_root, *, on_spawn=None, on_exit=None, initialize_stage=True):
    """Shared detached-worker handoff; parent never overwrites finished output."""
    import sys

    jd = job.job_dir(workspace_dir)
    lease = _take_claim(jd)
    if lease is None:
        return None
    read_fd = write_fd = None
    log = None
    proc = None
    try:
        read_fd, write_fd = os.pipe()
        log = open(jd / 'worker.log', 'w')
        env = dict(os.environ, **{_FD_ENV: str(lease.fd), _READY_ENV: str(read_fd)})
        proc = subprocess.Popen([sys.executable, '-m', module, str(workspace_dir), job.job_id],
            cwd=str(repo_root), stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            env=env, pass_fds=(lease.fd, read_fd))
        job.pid = proc.pid
        job.status = type(job.status)('running')
        for stage in (job.stages[:1] if initialize_stage else []):
            stage.status, stage.started_at = 'running', time.time()
        job.save(workspace_dir)
        if on_spawn is not None:
            on_spawn(proc)
        os.write(write_fd, b'1')
        return proc
    finally:
        if read_fd is not None:
            os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if log is not None:
            log.close()
        lease.close()
        if proc is not None:
            def reap():
                try:
                    proc.wait()
                finally:
                    if on_exit is not None:
                        on_exit()
            threading.Thread(target=reap, name=f'simulation-reap-{job.job_id}', daemon=True).start()
