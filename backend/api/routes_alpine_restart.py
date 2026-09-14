"""Acknowledgment changes attention state only, never scheduler or simulation state."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core import alpine_restart
from backend.core.md_job import MdJob

router = APIRouter()


class EventRevision(BaseModel):
    id: str
    revision: int = Field(ge=1)


class AcknowledgeRequest(BaseModel):
    events: list[EventRevision]


@router.post("/md/jobs/{job_id}/restart-acknowledgment")
def acknowledge_restart(job_id: str, body: AcknowledgeRequest):
    from backend.api.routes_md import _workspace

    workspace = _workspace()
    try:
        job = MdJob.load(job_id, workspace)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Job not found") from None
    try:
        alpine_restart.acknowledge(
            job, [e.model_dump() for e in body.events], workspace
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "restart_events": job.restart_events}
