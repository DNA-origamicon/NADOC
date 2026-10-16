"""Default-off HTTP authoring for separate group and placement records.

Only bounded JSON acquisition runs on the event loop. The shared owned recorder
and exact-candidate response run on the request thread; no native math lives here.
"""

from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from starlette.concurrency import run_in_threadpool

from backend.api import doc_context, part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
from backend.api.part_bounded_json import read_operation_json


router = APIRouter()
READ_SECONDS = 5.0
_input_slot = Lock()


class GroupCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["group-organize", "group-create", "group-update", "group-dissolve", "placement-update"]
    inputs: dict
    expected_revision: StrictInt = Field(ge=0)


async def _read_request(request):
    return await read_operation_json(request, prefix="group_edit", label="Group edit",
                                     slot=_input_slot, read_seconds=READ_SECONDS)


def _respond(value, generation):
    gate.require_group_edit_enabled()
    current = policy.require_compatibility(doc_context.get_current_doc(), "owned_group_edit")
    if current.generation != generation:
        raise HTTPException(409, detail={"code": "policy_changed",
            "detail": "Construction policy changed during request acquisition"})
    try:
        command = GroupCommandRequest.model_validate(value)
    except ValidationError as error:
        raise HTTPException(422, detail={"code": "invalid_group_edit_input", "detail": str(error)}) from error

    from backend.api import crud, part_group_organization_recording as host

    candidate, report, entry = host.apply(command.kind, command.inputs,
                                         expected_revision=command.expected_revision)
    response = (crud._design_response_with_geometry if command.kind == "placement-update"
                else crud._design_response)
    return ORJSONResponse(response(candidate, report, normalize_legacy=False,
                                  preserve_feature_log_id=entry.id if entry is not None else None))


@router.post("/design/group-organization/commands")
async def commands(request: Request):
    gate.require_group_edit_enabled()  # No body acquisition when disabled.
    doc = doc_context.get_current_doc()
    selected = policy.require_compatibility(doc, "owned_group_edit")
    try:
        require_document_identity(doc)
    except UnsafeDocumentIdentity as error:
        raise HTTPException(422, detail={"code": error.code, "detail": str(error)}) from error
    value = await _read_request(request)
    return await run_in_threadpool(_respond, value, selected.generation)
