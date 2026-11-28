"""Private assembly candidates, explicit atomic commit, and shared job cleanup."""
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
from backend.api.assembly_verification_jobs import AssemblyJob, _matches
from backend.api.assembly_evaluation import EvaluationRequest
from backend.api.assembly_evaluation_worker import AssemblyEvaluationWorker
from backend.api.part_history_verification import _slot
from backend.api.part_verification_jobs import supervise
from backend.core.part_capture_graph import CaptureLimit
from backend.core.part_history_proof import digest
from backend.core.models import Assembly

TIME_BUDGET = 180.0
RESULT_TTL = 900.0
MAX_RESULTS = 2
_lock = Lock()
_jobs = OrderedDict()


@dataclass
class EvaluationJob(AssemblyJob):
    assembly_id: str = ''
    request_sha256: str = ''
    source_sha256: str = ''
    committed_revision: int | None = None


def _run(job, captured, operation):
    result = supervise(job, captured, lambda source: AssemblyEvaluationWorker(source, operation), TIME_BUDGET,
                       status_lock=_lock, source_matches=lambda: _matches(job))
    result['assembly_id'] = result.pop('design_id')
    if result.get('status') == 'ready' and result.get('request_sha256') != job.request_sha256:
        result = {'status': 'unverified', 'native_editable': False, 'issues': [{'code': 'request_mismatch'}]}
    with _lock:
        job.result, job.status = result, 'complete'


def _submit(job, captured, operation):
    Thread(target=_run, args=(job, captured, operation), name='assembly-evaluation-supervisor', daemon=False).start()


def _lookup(identity):
    for key, job in list(_jobs.items()):
        if job.status in {'complete', 'committed'} and monotonic() - job.created > RESULT_TTL:
            del _jobs[key]
    job = _jobs.get(identity)
    if job is None or job.doc != get_current_doc():
        raise HTTPException(404, detail='Unknown assembly evaluation job')
    return job


def start(request):
    request = EvaluationRequest.model_validate(request)
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail='A history operation is already running')
    identity = None
    try:
        operation = request.model_dump(mode='json')
        operation = deepcopy(operation)
        session, source, captured, revision = assembly_state.capture_for_verification()
        if request.expected_revision != revision or request.expected_assembly_id != captured.id:
            raise HTTPException(409, detail='Assembly changed before evaluation started')
        job = EvaluationJob(get_current_doc(), ref(source), revision, session=ref(session), created=monotonic(),
                            assembly_id=captured.id, request_sha256=digest(operation), source_sha256=digest(captured.model_dump(mode='json')))
        identity = str(uuid4())
        with _lock:
            while len(_jobs) >= MAX_RESULTS:
                removable = next((key for key, value in _jobs.items() if value.status in {'complete', 'committed'}), None)
                if removable is None:
                    raise HTTPException(429, detail='Assembly evaluation registry is busy')
                del _jobs[removable]
            _jobs[identity] = job
        _submit(job, captured, operation)
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
        job = _lookup(identity)
        if cancel:
            job.cancelled.set()
            if job.result:
                job.result.pop('candidate', None)
        result = deepcopy({k: v for k, v in job.result.items() if k != 'candidate'}) if job.result else None
        status = job.status
    matches = _matches(job)
    stale, busy = matches is False, matches is None
    if result is not None and status != 'committed' and (stale or busy or job.cancelled.is_set()):
        result.update(status='unverified', native_editable=False)
        result['issues'].append({'code': 'cancelled' if job.cancelled.is_set() else 'source_changed' if stale else 'source_busy'})
    return {'job_id': identity, 'status': status, 'source_revision': job.revision,
            'stale': stale, 'source_busy': busy, 'result': result}


def commit(identity):
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail='A history operation is already running')
    try:
        with _lock:
            job = _lookup(identity)
            if job.committed_revision is not None:
                with assembly_state._lock:
                    if assembly_state._session() is not job.session():
                        raise HTTPException(409, detail='Evaluation belongs to an earlier assembly session')
                return {'job_id': identity, 'status': 'committed', 'revision': job.committed_revision, 'assembly_id': job.assembly_id}
            if job.cancelled.is_set() or job.status != 'complete' or not job.result or job.result.get('status') != 'ready':
                raise HTTPException(409, detail='Assembly evaluation has no publishable candidate')
            if _matches(job) is not True:
                job.result.pop('candidate', None)
                raise HTTPException(409, detail='Assembly changed; evaluate again')
            data = job.result.get('candidate')
            if not isinstance(data, dict) or digest(data) != job.result.get('candidate_sha256'):
                job.result.pop('candidate', None)
                raise HTTPException(409, detail='Assembly candidate integrity check failed')
            candidate = Assembly.model_validate(deepcopy(data))
            if digest(candidate.model_dump(mode='json')) != job.result['candidate_sha256']:
                raise HTTPException(409, detail='Assembly candidate changed during decoding')
            published = assembly_state.publish_candidate(candidate, source=job.source(), expected_revision=job.revision,
                expected_session=job.session(), expected_source_fingerprint=job.source_sha256)
            job.committed_revision = job.revision + 1
            job.status = 'committed'
            job.result.pop('candidate', None)
            return {'job_id': identity, 'status': 'committed', 'revision': job.committed_revision, 'assembly_id': published.id}
    except CaptureLimit as error:
        raise HTTPException(413, detail=str(error)) from error
    finally:
        _slot.release()
