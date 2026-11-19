"""Read-only capability checks for solver cluster cards."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Literal

from backend.core.solver_cluster_config import SolverClusterSettings

router = APIRouter(tags=['solver-cluster'])


class EnvironmentCheck(BaseModel):
    engine: Literal['snupi', 'mrdna']
    settings: SolverClusterSettings


@router.post('/solver-cluster/alpine-check')
async def check_environment(body: EnvironmentCheck):
    from backend.core.alpine_worker import WorkerClient
    from backend.core.solver_cluster import preflight
    try:
        await preflight(WorkerClient(), body.engine, body.settings)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'ok': True, 'message': 'Remote Python dependencies are available. GPU execution is checked on the allocated node.'}


@router.get('/solver-cluster/runpod-options')
async def runpod_options(mem_gb: int = Query(64, ge=1, le=2048), cores: int = Query(8, ge=1, le=256), include_unavailable: bool = False):
    from backend.api.routes_runpod import _SESSION
    from backend.core.solver_runpod_stock import fetch_solver_stock
    from backend.core.runpod_api import RunpodError
    if not _SESSION.is_connected():
        raise HTTPException(409, 'Connect RunPod first')
    try:
        stock = await fetch_solver_stock(_SESSION.api_key, _SESSION.network_volume_id, mem_gb, cores)
    except RunpodError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'gpus': [{'id': key, **row} for key, row in stock.items()
                     if (include_unavailable or (row.get('on_demand') and row.get('stock', 'none').lower() != 'none')) and 'AMD' not in key.upper()]}


@router.post('/solver-cluster/runpod-check')
async def runpod_account_check():
    from backend.api.routes_runpod import _SESSION, _ssh_key_present
    from backend.core.runpod_api import resolve_api_key
    connected = _SESSION.is_connected()
    checks = [
        {'key': 'api_key', 'ok': connected, 'label': 'RunPod connection', 'detail': 'Connected' if connected else 'Connect first'},
        {'key': 'volume', 'ok': bool(_SESSION.network_volume_id), 'label': 'Network volume', 'detail': _SESSION.network_volume_id or 'Choose a volume'},
        {'key': 'ssh_key', 'ok': _ssh_key_present(), 'label': 'SSH key', 'detail': 'Register the public key with RunPod'},
        {'key': 'watchdog', 'ok': connected and resolve_api_key(env={}).value == _SESSION.api_key, 'label': 'Budget watchdog key', 'detail': 'Requires the matching key in ~/.runpod_key'},
    ]
    return {'ok': all(row['ok'] for row in checks), 'checks': checks,
            'note': 'Account checks only. Live price is rechecked before renting. Host RAM/vCPU minima are requested at deployment; solver software is checked on the allocated pod; startup and transfers use the compute budget.'}
