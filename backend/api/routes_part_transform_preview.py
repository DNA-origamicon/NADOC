"""Disabled transform history editor using the common bounded lease transport."""

from fastapi import APIRouter, Request

from backend.api.routes_part_deformation_preview import _dispatch


router = APIRouter()
TRANSFORM_PREVIEW_ENABLED = False
_PATH = "/design/features/transform-preview"


@router.post(_PATH)
async def prepare(request: Request):
    return await _dispatch(request, "prepare", family="transform")


@router.post(_PATH + "/evaluate")
async def evaluate(request: Request):
    return await _dispatch(request, "evaluate", family="transform")


@router.post(_PATH + "/apply")
async def apply(request: Request):
    return await _dispatch(request, "apply", family="transform")


@router.post(_PATH + "/cancel")
async def cancel(request: Request):
    return await _dispatch(request, "cancel", family="transform")


@router.post(_PATH + "/status")
async def status(request: Request):
    return await _dispatch(request, "status", family="transform")
