"""Local Debug tour launcher. Only named repository workflows may execute."""
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from backend.api.routes_vr import _require_local, _read_state
from tools.vr_workflows.tour_catalog import ROOT, catalog, arguments, command

router = APIRouter(prefix='/vr/tours')
_lock = threading.RLock()
_run = None


class StartTour(BaseModel):
    tour: str
    mode: Literal['demo', 'validate', 'desktop'] = 'demo'
    assembly_active: bool = False


def _snapshot():
    if _run is None:
        return None
    process = _run['process']
    code = process.poll()
    log = _run['directory']/'tour.log'
    try:
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size-16000))
            tail = stream.read(16000).decode(errors='replace')
    except OSError:
        tail = ''
    return {k: _run[k] for k in ('id', 'tour', 'mode')} | {
        'status': ('stopping' if _run['stopping'] else 'running') if code is None else
                  ('stopped' if _run['stopping'] else 'passed' if code == 0 else 'failed'),
        'exit_code': code, 'output': str(_run['directory'].relative_to(ROOT)), 'log': tail,
    }


def _viewer_active():
    if _read_state():
        return True
    # Also detect standalone command-line tour viewers, which have no backend state.
    for path in Path('/proc').glob('[0-9]*/comm'):
        try:
            if path.read_text().strip().startswith('nadoc-vr-viewer'):
                return True
        except OSError:
            continue
    return False


@router.get('')
def list_tours(request: Request):
    _require_local(request, check_platform=False)
    data = catalog()
    for tour in data['tours']:
        tour['validation_command'] = command(tour, validate=True)
    with _lock:
        return {**data, 'run': _snapshot()}


@router.get('/status')
def status(request: Request):
    _require_local(request, check_platform=False)
    with _lock:
        return {'run': _snapshot()}


@router.post('/start')
def start(body: StartTour, request: Request):
    global _run
    _require_local(request)
    tour = next((t for t in catalog()['tours'] if t['id'] == body.tour), None)
    if not tour or not tour['runnable']:
        raise HTTPException(400, 'Choose a supported direct-launch tour.')
    if body.mode == 'desktop' and tour['module'] != 'component_gallery_tour':
        raise HTTPException(400, 'Desktop mode is only available for component galleries.')
    with _lock:
        if _run and _run['process'].poll() is None:
            raise HTTPException(409, 'A tour is already running. Stop it before starting another.')
        if body.mode != 'desktop' and _viewer_active():
            raise HTTPException(409, 'Close the active VR viewer before starting an isolated tour.')
        design = None
        if tour['module'] == 'representation_tour':
            from backend.api import state
            from backend.api.doc_context import get_current_doc
            if body.assembly_active:
                raise HTTPException(400, 'Open an individual design for the visualization demo.')
            design, _revision = state.copy_doc_for_persist(get_current_doc())
            if design is None:
                raise HTTPException(400, 'Open a design before starting the visualization demo.')
        identifier = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        directory = ROOT/'.development-artifacts/vr-debug-tours'/identifier
        directory.mkdir(parents=True)
        argv = [sys.executable, *arguments(tour, body.mode == 'validate'), '--output', str(directory/'evidence')]
        if body.mode == 'desktop':
            argv += ['--desktop']
        if design is not None:
            source = directory/'open-design.nadoc'
            source.write_text(design.to_json())
            argv += ['--design', str(source)]
        if tour['module'] == 'browser_representation_tour':
            from backend.api.doc_context import get_current_doc
            argv += ['--doc', get_current_doc()]
        env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'NADOC_DISABLE_SESSION_CACHE': '1'}
        try:
            with (directory/'tour.log').open('wb') as log:
                process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            raise HTTPException(503, f'Could not start the tour: {error}') from error
        _run = dict(id=identifier, tour=tour['id'], mode=body.mode, directory=directory,
                    process=process, stopping=False)
        return {'run': _snapshot()}


def _stop_process(process):
    # SIGINT lets the workflows release controller input and close owned viewers.
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


@router.post('/stop/{identifier}')
def stop(identifier: str, request: Request):
    _require_local(request, check_platform=False)
    with _lock:
        if not _run or identifier != _run['id']:
            raise HTTPException(409, 'That tour is no longer the current run.')
        if _run['process'].poll() is None and not _run['stopping']:
            _run['stopping'] = True
            threading.Thread(target=_stop_process, args=(_run['process'],), daemon=True).start()
        return {'run': _snapshot()}


def shutdown_tours():
    """Close the owned tour when the development server reloads or shuts down."""
    with _lock:
        process = _run['process'] if _run else None
        if not process or process.poll() is not None or _run['stopping']:
            return
        _run['stopping'] = True
    _stop_process(process)
