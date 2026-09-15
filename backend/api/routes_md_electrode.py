"""Explicit continuation of a completed but unqualified electrode relaxation."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.core.namd_electrode_continue import extend_equilibration

router=APIRouter(tags=['md'])

class ElectrodeExtensionRequest(BaseModel):
    duration_ns: float = Field(2.4,gt=0,le=100,allow_inf_nan=False)

@router.post('/md/jobs/{job_id}/extend-electrode-equilibration')
def extend_electrode_job(job_id: str, body: ElectrodeExtensionRequest):
    from backend.api.routes_md import _workspace
    try:
        job=extend_equilibration(job_id,_workspace(),body.duration_ns)
    except (ValueError,OSError,KeyError) as exc:
        raise HTTPException(409,str(exc)) from exc
    return {'job_id':job.job_id,'status':job.status.value,'added_ns':body.duration_ns}
