"""Opt-in Exp screening controls; never launches NAMD or uses a GPU."""

from fastapi import APIRouter, HTTPException

from backend.api import state
from backend.api.doc_context import get_current_doc
from backend.core.exp_predictor import ModelUnavailable, predictor

router = APIRouter(prefix="/exp", tags=["exp"])


@router.get("/status")
def status():
    return predictor.status()


@router.post("/jobs")
def start():
    try:
        return predictor.start(get_current_doc(), state.get_or_404())
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs/{job_id}")
def get(job_id: str):
    try:
        return predictor.get(get_current_doc(), job_id)
    except KeyError as exc:
        raise HTTPException(404, "Exp prediction not found in this document") from exc


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str):
    try:
        return predictor.stop(get_current_doc(), job_id)
    except KeyError as exc:
        raise HTTPException(404, "Exp prediction not found in this document") from exc


@router.get("/jobs/{job_id}/snapshot-geometry")
def snapshot_geometry(job_id: str):
    try:
        return predictor.snapshot_geometry(get_current_doc(), job_id)
    except KeyError as exc:
        raise HTTPException(404, "Exp prediction not found in this document") from exc
