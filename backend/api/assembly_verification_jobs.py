"""Document/session/revision-bound assembly proof jobs; never publish candidates."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock, Thread
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.doc_context import get_current_doc
from backend.api.part_history_verification import _slot
from backend.api.part_verification_jobs import Job, supervise
from backend.api.assembly_verification_worker import AssemblyVerificationWorker
from backend.core.part_capture_graph import CaptureLimit

TIME_BUDGET = 180.0
MAX_RESULTS = 8
RESULT_TTL = 900.0
_lock = Lock()
_jobs = OrderedDict()


@dataclass
class AssemblyJob(Job):
    session: object = None
    created: float = 0


def _matches(job):
    return assembly_state.verification_source_matches(job.doc, job.session(), job.source(), job.revision)


def _run(job, captured):
    result = supervise(job, captured, AssemblyVerificationWorker, TIME_BUDGET,
                       status_lock=_lock, source_matches=lambda: _matches(job))
    result['assembly_id'] = result.pop('design_id')
    with _lock:
        job.result, job.status = result, 'complete'


def _submit(job, captured):
    Thread(target=_run, args=(job, captured), name='assembly-proof-supervisor', daemon=False).start()


def _expire():
    for identity, job in list(_jobs.items()):
        if job.status == 'complete' and monotonic() - job.created > RESULT_TTL:
            del _jobs[identity]


def start(*, expected_revision=None):
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail='A history operation is already running')
    identity = None
    try:
        session, source, captured, revision = assembly_state.capture_for_verification()
        if expected_revision is not None and expected_revision != revision:
            raise HTTPException(409, detail='Assembly changed before verification started')
        job = AssemblyJob(get_current_doc(), ref(source), revision, session=ref(session), created=monotonic())
        identity = str(uuid4())
        with _lock:
            _expire()
            while len(_jobs) >= MAX_RESULTS:
                removable = next((key for key, value in _jobs.items() if value.status == 'complete'), None)
                if removable is None:
                    raise HTTPException(429, detail='Assembly verification registry is busy')
                del _jobs[removable]
            _jobs[identity] = job
        _submit(job, captured)
        return {'job_id': identity, 'status': 'running', 'source_revision': revision, 'assembly_id': captured.id}
    except BaseException as error:
        if identity is not None:
            with _lock:
                _jobs.pop(identity, None)
        _slot.release()
        if isinstance(error, CaptureLimit):
            raise HTTPException(413, detail=str(error)) from error
        raise


def inspect(identity, *, cancel=False):
    with _lock:
        _expire()
        job = _jobs.get(identity)
        if job is None or job.doc != get_current_doc():
            raise HTTPException(404, detail='Unknown assembly verification job')
        if cancel:
            job.cancelled.set()
        result, status = deepcopy(job.result), job.status
    matches = _matches(job)
    stale, busy = matches is False, matches is None
    if result is not None and (stale or busy or job.cancelled.is_set()):
        result['status'], result['native_editable'] = 'unverified', False
        result['issues'].append({'code': 'cancelled' if job.cancelled.is_set() else 'source_changed' if stale else 'source_busy'})
    return {'job_id': identity, 'status': status, 'source_revision': job.revision,
            'stale': stale, 'source_busy': busy, 'result': result}
