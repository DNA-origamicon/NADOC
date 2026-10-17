"""Validate and commit clipboard snapshots; no mutation occurs on Copy."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.core.models import Design
from backend.core.vr_clipboard import paste_snapshot, rigid_matrix, preview_snapshot
from backend.api import state
from backend.api.crud import _design_response
from backend.core.cluster_reconcile import MutationReport

router = APIRouter()

class ClipboardBody(BaseModel):
    source: Design
    refs: list[dict] = Field(min_length=1, max_length=4096)
    matrix: list[float] = Field(min_length=16, max_length=16)

@router.post('/vr/clipboard/validate')
def validate(body: ClipboardBody):
    try:
        paste_snapshot(body.source, body.source, body.refs, rigid_matrix(body.matrix))
        preview = preview_snapshot(body.source, body.refs)
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    return {'accepted': True, 'preview': preview}

@router.post('/vr/clipboard/paste')
def paste(body: ClipboardBody):
    def mutate(design):
        if design.id != body.source.id:
            raise HTTPException(409, detail='Clipboard belongs to another design')
        try:
            result, helices = paste_snapshot(design, body.source, body.refs, rigid_matrix(body.matrix))
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
        return result, MutationReport(new_helix_origins={h: None for h in helices})
    updated, report, _ = state.mutate_with_feature_log(
        op_kind='element-paste', label='Paste selected elements in VR',
        params={'refs': body.refs, 'matrix': body.matrix}, fn=mutate)
    return _design_response(updated, report)
