"""Sweep history editor; shares bounded transport and owned leases."""

from fastapi import APIRouter, Request

from backend.api.routes_part_deformation_preview import _dispatch


router = APIRouter()
SWEEP_PREVIEW_ENABLED = True
_PATH = "/design/features/sweep-preview"


@router.post(_PATH)
async def prepare(request: Request):
    return await _dispatch(request, "prepare", family="sweep")


@router.post(_PATH + "/evaluate")
async def evaluate(request: Request):
    return await _dispatch(request, "evaluate", family="sweep")


@router.post(_PATH + "/apply")
async def apply(request: Request):
    return await _dispatch(request, "apply", family="sweep")


@router.post(_PATH + "/cancel")
async def cancel(request: Request):
    return await _dispatch(request, "cancel", family="sweep")


@router.post(_PATH + "/status")
async def status(request: Request):
    return await _dispatch(request, "status", family="sweep")
