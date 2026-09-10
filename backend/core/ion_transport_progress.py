"""Thread-safe, bounded progress snapshots for ion-transport requests."""
from collections import OrderedDict
from threading import Lock
import time

_runs = OrderedDict()
_lock = Lock()


def start(job_id, request_id):
    with _lock:
        _runs[(job_id, request_id)] = {'request_id': request_id, 'state': 'running', 'stages': [], 'started_at': time.time()}
        while len(_runs) > 64:
            _runs.popitem(last=False)


def update(job_id, request_id, stage, done=0, total=0, detail=''):
    with _lock:
        run = _runs.get((job_id, request_id))
        if run is None:
            return
        item = {'stage': stage, 'done': done, 'total': total, 'detail': detail,
                'state': 'done' if total > 0 and done >= total else 'running'}
        stages = {entry['stage']: entry for entry in run['stages']}
        stages[stage] = item
        run['stages'] = list(stages.values())


def finish(job_id, request_id, error=None):
    with _lock:
        run = _runs.get((job_id, request_id))
        if run is not None:
            run['state'] = 'error' if error else 'done'
            run['error'] = error
            if error:
                run['stages'] = [dict(stage, state='error') if stage['state'] == 'running' else stage
                                 for stage in run['stages']]


def snapshot(job_id, request_id):
    with _lock:
        run = _runs.get((job_id, request_id))
        if run is None:
            return {'request_id': request_id, 'state': 'pending', 'stages': []}
        return {**run, 'stages': [dict(stage) for stage in run['stages']]}
