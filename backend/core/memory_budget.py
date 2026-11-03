"""Cross-process reservations for additional local allocations.

MemAvailable already excludes live application memory. For a separately owned
child we reserve only its still-unallocated growth; in-process work receives no
RSS credit, since attributing a shared interpreter's RSS to a request is unsafe.
Reservations are forecasts, not kernel limits or statistical guarantees.
"""
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import fcntl
import gc
import json
import os
import tempfile
import threading
import uuid
import time

import psutil

MIB = 1024**2
SYSTEM_RESERVE_BYTES = 4 * 1024**3
_reclaimers = {}
_thread_lock = threading.RLock()
_analysis_activity = ContextVar('exclusive_analysis_activity', default=False)
_trajectory_activity = ContextVar('trajectory_activity', default=None)


class MemoryBudgetExceeded(MemoryError):
    pass


class WorkloadBusy(MemoryBudgetExceeded):
    """A managed workload must finish before this activity can begin."""


def register_reclaimer(name, callback):
    _reclaimers[name] = callback


def reclaim_discretionary_memory():
    for callback in tuple(_reclaimers.values()):
        callback()
    gc.collect()


def _directory():
    root = Path(os.environ.get('NADOC_MEMORY_BUDGET_DIR',
                str(Path(tempfile.gettempdir()) / f'nadoc-memory-{os.getuid()}')))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise MemoryBudgetExceeded('Memory reservation directory must be private')
    return root


def _identity(pid):
    try:
        p = psutil.Process(pid)
        return {'pid': pid, 'created': p.create_time()}
    except psutil.Error:
        return None


def _process(identity):
    if not identity:
        return None
    try:
        p = psutil.Process(identity['pid'])
        return p if p.create_time() == identity['created'] and p.status() != psutil.STATUS_ZOMBIE else None
    except psutil.AccessDenied as exc:
        raise MemoryBudgetExceeded('Cannot verify a process holding a memory reservation') from exc
    except psutil.NoSuchProcess:
        return None


@contextmanager
def _locked():
    with _thread_lock:
        root = _directory()
        with (root / 'registry.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield root


def _records(root):
    records = []
    for path in root.glob('*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise MemoryBudgetExceeded('Cannot verify an existing memory reservation') from exc
        if (not isinstance(record, dict) or not isinstance(record.get('owner'), dict)
                or not {'pid', 'created'} <= record['owner'].keys()
                or not isinstance(record.get('bytes'), int)
                or (record['bytes'] <= 0 and not (record['bytes'] == 0
                    and record.get('scheduling_only') is True and record.get('kind') in ('heavy_analysis','trajectory_activity')))
                or not isinstance(record.get('kind'), str)):
            raise MemoryBudgetExceeded('Invalid existing memory reservation')
        if _process(record['owner']) is None and _process(record.get('child')) is None:
            path.unlink(missing_ok=True)
            continue
        records.append(record)
    return records


def _remaining(record):
    child = _process(record.get('child'))
    credit = 0
    if child is not None:
        try:
            # Private RSS avoids crediting shared pages repeatedly across children.
            credit = child.memory_full_info().uss
        except psutil.Error:
            pass
    return max(0, record['bytes'] - credit)


def available_for_work(available_bytes=None):
    with _locked() as root:
        current = psutil.virtual_memory().available if available_bytes is None else available_bytes
        return max(0, current - SYSTEM_RESERVE_BYTES
                   - sum(_remaining(r) for r in _records(root)))


def simulation_active():
    with _locked() as root:
        return any(r['kind'] == 'simulation' for r in _records(root))


class Reservation:
    def __init__(self, amount, kind, label, gpu_mib=0, devices='0', scheduling_only=False):
        self.amount, self.kind, self.label = int(amount), kind, label
        self.gpu_mib, self.devices = gpu_mib, devices
        self.scheduling_only = scheduling_only
        self.path = None

    def __enter__(self):
        if self.amount <= 0 and not (self.amount == 0 and self.scheduling_only and self.kind == 'heavy_analysis'):
            raise ValueError('Reservation must be positive')
        with _locked() as root:
            records = _records(root)
            if self.kind == 'simulation' and any(r['kind'] == 'heavy_analysis' for r in records):
                raise WorkloadBusy('Heavy trajectory analysis is running. Wait for it to finish before starting a local simulation.')
            if self.kind == 'heavy_analysis' and any(r['kind'] in ('simulation','heavy_analysis') for r in records):
                raise WorkloadBusy('Waiting for local simulation or trajectory analysis to finish')
            free = psutil.virtual_memory().available - SYSTEM_RESERVE_BYTES
            free -= sum(_remaining(r) for r in records)
            if self.amount > free:
                raise MemoryBudgetExceeded(
                    f'{self.label} requires {self.amount / MIB:.0f} MiB of additional RAM; '
                    f'{max(0, free) / MIB:.0f} MiB remains after active reservations and system reserve. '
                    'Close unused views, wait for other work, or use a larger machine.')
            if self.gpu_mib:
                from backend.core.md_vram import detect_gpu_activity
                if not str(self.devices).strip().isdigit():
                    raise MemoryBudgetExceeded('Memory admission currently requires one numeric GPU device; multiple GPUs need separate qualification')
                self.devices = str(int(str(self.devices).strip()))
                gpu = detect_gpu_activity(devices=self.devices)
                if not gpu or gpu.get('used_mb') is None or gpu.get('total_mb') is None:
                    raise MemoryBudgetExceeded('GPU availability could not be measured')
                # Conservatively reserve other jobs in full: no attribution of
                # shared CUDA/driver pages, and no race between two launch checks.
                pending = sum(r.get('gpu_mib', 0) for r in records
                              if r.get('devices') == self.devices)
                if self.gpu_mib + pending > gpu['total_mb'] - gpu['used_mb']:
                    raise MemoryBudgetExceeded('GPU memory is reserved or unavailable; select CUDA offload or a larger GPU')
            self.record = {'owner': _identity(os.getpid()), 'child': None,
                           'bytes': self.amount, 'kind': self.kind, 'label': self.label,
                           'scheduling_only': self.scheduling_only,
                           'gpu_mib': self.gpu_mib, 'devices': self.devices}
            self.path = root / (uuid.uuid4().hex + '.json')
            self.path.write_text(json.dumps(self.record))
        return self

    def bind_child(self, pid):
        with _locked():
            self.record['child'] = _identity(pid)
            self.path.write_text(json.dumps(self.record))

    def __exit__(self, *exc):
        if self.path is not None:
            with _locked():
                self.path.unlink(missing_ok=True)


def reserve(amount, *, kind='analysis', label='Analysis', gpu_mib=0, devices='0'):
    return Reservation(amount, kind, label, gpu_mib, devices)


def analysis_activity_lease():
    """Nonblocking scheduling lease for async callers; no memory bound is implied."""
    return Reservation(0,'heavy_analysis','Heavy trajectory analysis',scheduling_only=True)


class TrajectoryActivity:
    """One active topology/trajectory operation across API processes and views.

    Pending work allocates no interpreter. Health has priority over queued
    playback; equal-priority requests use FIFO order. This is a scheduling lease,
    not a RAM estimate. Binding a worker keeps the slot live if its owner exits.
    """
    def __init__(self, kind):
        if kind not in ('health','playback','bulk'):
            raise ValueError('Unknown trajectory activity')
        self.kind=kind;self.path=None

    def try_acquire(self):
        with _locked() as root:
            records=_records(root)
            if self.path is None:
                self.record=dict(owner=_identity(os.getpid()),child=None,bytes=0,
                    kind='trajectory_activity',scheduling_only=True,label=self.kind,
                    priority=0 if self.kind=='health' else 1,
                    ticket=time.monotonic_ns(),active=False,token=uuid.uuid4().hex)
                self.path=root/(self.record['token']+'.json')
                self.path.write_text(json.dumps(self.record));records.append(self.record)
            queue=[r for r in records if r['kind']=='trajectory_activity']
            if any(type(r.get('ticket')) is not int or r.get('priority') not in (0,1)
                   or type(r.get('active')) is not bool or not r.get('token') for r in queue):
                raise MemoryBudgetExceeded('Invalid trajectory scheduling record')
            if self.record['active']:
                return True
            if any(r['active'] for r in queue):
                return False
            first=min(queue,key=lambda r:(r['priority'],r['ticket'],r['token']))
            if first['token']!=self.record['token']:
                return False
            self.record['active']=True
            self.path.write_text(json.dumps(self.record))
            return True

    def bind_child(self, pid):
        with _locked():
            self.record['child']=_identity(pid)
            self.path.write_text(json.dumps(self.record))

    def close(self):
        if self.path is not None:
            with _locked():
                self.path.unlink(missing_ok=True)
            self.path=None


def current_trajectory_activity():
    return _trajectory_activity.get()


@asynccontextmanager
async def trajectory_activity(kind, *, cancel=None):
    import asyncio
    if _trajectory_activity.get() is not None:
        yield _trajectory_activity.get()
        return
    lease=TrajectoryActivity(kind)
    token=None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError()
            if lease.try_acquire():
                break
            await asyncio.sleep(.05)
        token=_trajectory_activity.set(lease)
        yield lease
    finally:
        if token is not None:_trajectory_activity.reset(token)
        lease.close()


@contextmanager
def exclusive_analysis(*, on_wait=None, cancel=None, poll_seconds=.5):
    """Queue a heavy analysis behind local simulations and other heavy analyses.

    Scheduling is atomic with simulation admission across processes. This lease
    does not estimate the analysis's memory: buffer limits/reservations remain
    separate. Use in background workers, never the API event loop. Nested work
    in the same execution context shares its parent's scheduling lease.
    """
    if _analysis_activity.get():
        yield
        return
    cancel = cancel if cancel is not None else threading.Event()
    lease = analysis_activity_lease()
    notified=False
    while True:
        if cancel.is_set():
            raise InterruptedError('Queued analysis cancelled')
        try:
            lease.__enter__()
            break
        except WorkloadBusy as exc:
            if on_wait is not None and not notified:
                on_wait(str(exc));notified=True
            cancel.wait(poll_seconds)
    activity=TrajectoryActivity('bulk')
    token=None;trajectory_token=None
    try:
        while True:
            if cancel.is_set():raise InterruptedError('Queued analysis cancelled')
            if activity.try_acquire():break
            cancel.wait(poll_seconds)
        token=_analysis_activity.set(True)
        trajectory_token=_trajectory_activity.set(activity)
        from backend.core.md_playback_workers import close
        close()
        yield
    finally:
        if token is not None:_analysis_activity.reset(token)
        if trajectory_token is not None:_trajectory_activity.reset(trajectory_token)
        activity.close()
        lease.__exit__(None,None,None)


def check_array_budget(amount, *, maximum=128 * MIB):
    """Reject oversized response buffers before allocation; callers can page them."""
    if amount > maximum:
        raise MemoryBudgetExceeded(
            f'Trajectory response needs {amount / MIB:.0f} MiB; the buffer limit is '
            f'{maximum / MIB:.0f} MiB. Request a smaller frame range.')


def reserve_trajectory_response(function):
    """Keep extraction and binary packing inside one admitted buffer allowance."""
    @wraps(function)
    def build(*args, **kwargs):
        with reserve(128 * MIB, label='Trajectory response buffers'):
            return function(*args, **kwargs)
    return build
