"""Bounded, cancellable EM computation on a supplied optical snapshot; no design writes."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

router = APIRouter(prefix='/em-analysis', tags=['experimental EM'])
_lock = asyncio.Lock()
ROOT = Path(__file__).resolve().parents[2]


class Particle(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(max_length=200)
    center_nm: tuple[float, float, float]
    diameter_nm: float = Field(ge=5, le=100)


class DNAShell(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: Literal['none', 'ssdna_wlc', 'manual'] = 'none'
    oligo_length_nt: int = Field(default=20, ge=1, le=200)
    persistence_length_nm: float = Field(default=2.5, ge=0.1, le=10)
    thickness_nm: float = Field(default=2.5, ge=0, le=100)
    refractive_index: float = Field(default=1.7, ge=1, le=2.5)


class EMRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    particles: list[Particle] = Field(min_length=1, max_length=4)
    polarization: Literal['parallel', 'perpendicular'] = 'parallel'
    resolution: Literal[25, 33, 49] = 33
    sampling: Literal['uniform', 'adaptive', 'field_adaptive'] = 'uniform'
    solver: Literal['multipole', 'multipole_reference'] = 'multipole'
    shell: DNAShell = Field(default_factory=DNAShell)


def solver_python():
    override = os.environ.get('NADOC_EM_PYTHON')
    if override:
        return override if Path(override).is_file() else None
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    candidate = data / 'nadoc/engines/em/.venv/bin/python'
    if candidate.is_file():
        return str(candidate)
    return sys.executable if importlib.util.find_spec('miepy') else None


@router.get('/status')
def status():
    return {'available': solver_python() is not None, 'busy': _lock.locked(),
            'install': 'See docs/em_analysis.md for the isolated MiePy 1.1.0 installation.'}


async def run_solver(payload, request):
    executable = solver_python()
    if not executable:
        raise HTTPException(503, 'EM solver is not installed. See docs/em_analysis.md.')
    if _lock.locked():
        raise HTTPException(409, 'An EM analysis is already running. Try again when it finishes.')
    async with _lock:
        env = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
               'MKL_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1', 'MPLBACKEND': 'Agg'}
        process = await asyncio.create_subprocess_exec(executable, '-m', 'backend.physics.em_analysis',
            cwd=ROOT, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        communication = asyncio.create_task(process.communicate(json.dumps(payload).encode()))
        try:
            async with asyncio.timeout(180):
                while not communication.done():
                    if await request.is_disconnected():
                        raise HTTPException(499, 'EM analysis cancelled.')
                    await asyncio.wait({communication}, timeout=.2)
                stdout, _ = await communication
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(500, 'EM solver failed without a valid result.') from None
            if process.returncode or 'error' in result:
                raise HTTPException(422, result.get('error', 'EM solver failed.'))
            return result
        except TimeoutError:
            raise HTTPException(504, 'EM analysis exceeded the 180 second experimental limit. Try the coarser grid.') from None
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            if not communication.done():
                communication.cancel()
            await asyncio.gather(communication, return_exceptions=True)


@router.post('/solve')
async def analyze(payload: EMRequest, request: Request):
    return await run_solver(payload.model_dump(), request)


from backend.api.em_trajectory_jobs import mount_trajectory_routes
mount_trajectory_routes(router, EMRequest, solver_python, ROOT, _lock)
