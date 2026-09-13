"""Read-only display of persisted PEG qualification jobs."""
import re

from fastapi import APIRouter, HTTPException, Query

from backend.core.namd_peg_review import job_review

router = APIRouter(prefix='/md/peg-qualifications', tags=['NAMD PEG qualification'])


@router.get('/{job_id}')
def get_review(job_id: str, segment: str | None = None, max_frames: int = Query(100, ge=1, le=200)):
    from backend.api.assembly import _WORKSPACE_DIR
    if not re.fullmatch(r'[a-f0-9]{12}', job_id):
        raise HTTPException(422, 'Invalid job ID')
    try:
        return job_review(_WORKSPACE_DIR, job_id, segment=segment, max_frames=max_frames)
    except FileNotFoundError:
        raise HTTPException(404, 'PEG qualification result not found') from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/{job_id}/fast-relax')
def create_fast_relax(job_id: str):
    """Prepare a fresh local child; the ordinary job Run/Stop/Resume controls execute it."""
    from dataclasses import asdict
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.core.namd_peg_relax import prepare_relax
    if not re.fullmatch(r'[a-f0-9]{12}', job_id):
        raise HTTPException(422, 'Invalid job ID')
    try:
        return asdict(prepare_relax(_WORKSPACE_DIR, job_id))
    except FileNotFoundError:
        raise HTTPException(404, 'PEG source not found') from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
