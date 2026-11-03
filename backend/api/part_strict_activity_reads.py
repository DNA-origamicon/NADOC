"""Closed, request-owned activity reads; incomplete catalogs never fall back."""
import asyncio
from pathlib import Path
import stat
from threading import Event
from time import monotonic

from fastapi import HTTPException, Request

from backend.api import state, assembly
from backend.api.part_async_work import thread_call
from backend.api.part_history_verification import _slot
from backend.api.part_strict_reads import _require_context_locked
from backend.api.part_strict_service_reads import capture, response
from backend.core.activity_catalog import activity_catalog
from backend.core.activity_evidence_io import Evidence, MAX_SECONDS


def _check(request, captured):
    context, session, identity = captured
    with state._lock:
        _require_context_locked(request)
        current = state._sessions.get(context.doc_id)
        if current is not session or (current is not None and current.identity != identity):
            raise HTTPException(409, detail={'code': 'status_session_changed'})


def _workspace_stamp(workspace):
    try:
        if len(str(workspace)) > 4096:
            raise ValueError('Workspace path exceeds its allowance')
        info = workspace.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Workspace is not a directory')
        return info.st_dev, info.st_ino
    except (OSError, ValueError):
        raise HTTPException(503, detail={'code': 'activity_workspace_unavailable'}) from None


def _read(request, captured, workspace, cancelled, deadline):
    evidence = Evidence(cancelled=cancelled)
    evidence.deadline = min(evidence.deadline, deadline)
    _check(request, captured)
    stamp = _workspace_stamp(workspace)
    catalog = activity_catalog(workspace, evidence=evidence)
    _check(request, captured)
    if cancelled.is_set():
        raise HTTPException(409, detail={'code': 'activity_cancelled'})
    if monotonic() >= evidence.deadline:
        raise HTTPException(408, detail={'code': 'activity_time_limit'})
    if Path(assembly._WORKSPACE_DIR).absolute() != workspace or _workspace_stamp(workspace) != stamp:
        raise HTTPException(409, detail={'code': 'activity_workspace_changed'})
    if catalog.get('complete') is not True:
        # Do not leak job metadata in a refusal or claim count=0 for unknown work.
        reasons = [issue.get('reason', '') for issue in catalog.get('issues', [])]
        reasons.extend(reason for record in catalog.get('records', []) for reason in record.get('issues', []))
        limited = any(reason.endswith('_budget') for reason in reasons)
        raise HTTPException(413 if limited else 409, detail={'code':
            'activity_evidence_limit' if limited else 'activity_evidence_incomplete'})
    records = catalog['records']
    if any(record['active'] is None or record['issues'] for record in records):
        raise HTTPException(409, detail={'code': 'activity_evidence_incomplete'})
    jobs = [record['summary'] for record in records if record['active'] is True]
    result = response(request, captured, {
        'jobs': jobs, 'count': len(jobs),
        'any_running': any(job['status'] == 'running' for job in jobs),
    })
    if Path(assembly._WORKSPACE_DIR).absolute() != workspace or _workspace_stamp(workspace) != stamp:
        raise HTTPException(409, detail={'code': 'activity_workspace_changed'})
    if cancelled.is_set() or monotonic() >= evidence.deadline:
        raise HTTPException(409 if cancelled.is_set() else 408,
                            detail={'code': 'activity_cancelled' if cancelled.is_set() else 'activity_time_limit'})
    _check(request, captured)
    return result


async def active_jobs(request: Request):
    captured = capture(request)
    if not _slot.acquire(blocking=False, background=True):
        raise HTTPException(429, detail={'code': 'activity_busy'})
    deadline = monotonic() + MAX_SECONDS
    cancelled, stopped = Event(), Event()
    watcher = None
    try:
        workspace = Path(assembly._WORKSPACE_DIR).absolute()
        from backend.api.part_recipe_file_transport import _watch_disconnect
        watcher = asyncio.create_task(_watch_disconnect(request, cancelled, stopped))
        return await thread_call(_read, request, captured, workspace, cancelled, deadline, cancelled=cancelled)
    finally:
        stopped.set()
        try:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
        finally:
            _slot.release()
