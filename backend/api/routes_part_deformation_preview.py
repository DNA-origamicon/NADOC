"""Private, disabled HTTP adapter for owned deformation-editor leases.

Only bounded input JSON is acquired on the event loop. Native work and explicit
response serialization use the request thread. Disconnecting an HTTP request is
not cancellation or rollback; the caller-known nonce and status endpoint resolve
that lifecycle. The strict route table deliberately does not admit this router.
"""

from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import ORJSONResponse
from starlette.concurrency import run_in_threadpool

from backend.api import doc_context, part_publication_policy as policy
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
from backend.api.part_bounded_json import read_operation_json


router = APIRouter()
DEFORMATION_PREVIEW_ENABLED = False
READ_SECONDS = 5.0
_input_slot = Lock()  # one nonqueued body acquisition; never held during host work
_PATH = "/design/features/deformation-preview"


def _fail(status, code, detail):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _enabled(family="deformation"):
    if family == "sweep":
        from backend.api.routes_part_sweep_preview import SWEEP_PREVIEW_ENABLED

        enabled = SWEEP_PREVIEW_ENABLED
    elif family == "deformation":
        enabled = DEFORMATION_PREVIEW_ENABLED
    else:
        _fail(422, "invalid_preview_family", "Unknown preview family")
    if not enabled:
        _fail(403, "preview_disabled", f"The isolated {family} editor is not enabled on this host")


async def _read_request(request):
    return await read_operation_json(request, prefix="preview", label="Preview",
                                     slot=_input_slot, read_seconds=READ_SECONDS)


def _respond(operation, value, generation, family="deformation"):
    _enabled(family)
    current = policy.require_compatibility(doc_context.get_current_doc(), f"{family}_preview")
    if current.generation != generation:
        _fail(409, "policy_changed", "Construction policy changed during request acquisition")
    from backend.api import part_deformation_preview_sessions as host

    # The DTO has already bounded the whole response, including host identity.
    # Returning Response avoids FastAPI's generic coordinate traversal; only the
    # actual final JSON encoding remains, on this worker thread.
    options = {} if family == "deformation" else {"family": family}
    return ORJSONResponse(getattr(host, operation)(value, **options))


async def _dispatch(request, operation, *, family="deformation"):
    _enabled(family)  # disabled means no body acquisition or native host import
    doc = doc_context.get_current_doc()
    selected = policy.require_compatibility(doc, f"{family}_preview")
    try:
        require_document_identity(doc)
    except UnsafeDocumentIdentity as error:
        _fail(422, error.code, str(error))
    value = await _read_request(request)
    if family == "deformation":
        return await run_in_threadpool(_respond, operation, value, selected.generation)
    return await run_in_threadpool(_respond, operation, value, selected.generation, family)


@router.post(_PATH)
async def prepare(request: Request):
    return await _dispatch(request, "prepare")


@router.post(_PATH + "/create")
async def create(request: Request):
    return await _dispatch(request, "prepare_create")


@router.post(_PATH + "/evaluate")
async def evaluate(request: Request):
    return await _dispatch(request, "evaluate")


@router.post(_PATH + "/apply")
async def apply(request: Request):
    return await _dispatch(request, "apply")


@router.post(_PATH + "/cancel")
async def cancel(request: Request):
    return await _dispatch(request, "cancel")


@router.post(_PATH + "/status")
async def status(request: Request):
    return await _dispatch(request, "status")
