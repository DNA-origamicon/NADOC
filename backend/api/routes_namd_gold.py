"""Bare-gold preparation and qualification continuation; no new frontend controls."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.core.gold_model import MODEL_ID, specification
from backend.core.namd_gold_job import prepare_job, extend_job

router = APIRouter(prefix="/md/gold", tags=["NAMD gold qualification"])


class GoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometry: dict
    model_id: str = MODEL_ID
    design_name: str = Field("Gold interface qualification", min_length=1, max_length=120)
    mobility: str = "restrained"
    restraint_k: float = Field(10., gt=0, le=100, allow_inf_nan=False)
    salt_mM: float = Field(150., ge=0, le=1000, allow_inf_nan=False)
    temperature_K: float = Field(298.15, ge=270, le=330, allow_inf_nan=False)
    seed: int = Field(17, ge=1, lt=2147483647)
    steps: int = Field(10000, ge=10, le=100000)
    timestep_fs: float = Field(1., allow_inf_nan=False)
    water_loading_scale: float = Field(1., ge=.9, le=1.3, allow_inf_nan=False)


class GoldContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: int = Field(10000, ge=10, le=100000)


@router.get("/model")
def gold_specification():
    return {"model": specification(), "physical_qualification": False}


@router.post("/jobs")
def create_gold_job(body: GoldRequest):
    from backend.api.routes_md import _workspace
    values = body.model_dump()
    geometry = values.pop("geometry")
    try:
        job = prepare_job(_workspace(), geometry, **values)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value, "physical_qualification": False,
            "start_url": f"/api/md/jobs/{job.job_id}/start"}


@router.post("/jobs/{job_id}/continue")
def continue_gold_job(job_id: str, body: GoldContinuation):
    from backend.api.routes_md import _workspace
    try:
        job = extend_job(job_id, _workspace(), steps=body.steps)
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value, "physical_qualification": False}
