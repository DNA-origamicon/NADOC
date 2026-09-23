"""Atomic authoring of an independently placed canonical lattice frame.

The caller resolves the source plane and converts tracking coordinates to part
coordinates. This endpoint never treats headset metres as molecular coordinates.
"""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from backend.api import state
from backend.core.lattice_frames import append_independent_bundle, append_frame_bundle

router = APIRouter()


class FrameExtrusionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_design_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0, strict=True)
    cells: list[list[StrictInt]] = Field(min_length=1, max_length=16641)
    length_bp: StrictInt
    plane: Literal['XY', 'XZ', 'YZ']
    translation_nm: list[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    rotation_xyzw: list[float] = Field(default_factory=lambda: [0, 0, 0, 1], min_length=4, max_length=4)
    source_frame_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(default='Extrude', min_length=1, max_length=128)


def _candidate(design, body):
    if design.id != body.expected_design_id:
        raise HTTPException(409, detail='Active design changed')
    # Keep a single interactive operation within bounded topology construction.
    if len(body.cells) * abs(body.length_bp) > 200_000:
        raise HTTPException(422, detail='Extrusion exceeds 200000 base-pair cells')
    try:
        if body.source_frame_id is not None:
            if body.translation_nm != [0, 0, 0] or body.rotation_xyzw != [0, 0, 0, 1]:
                raise ValueError('source frame already supplies rigid placement')
            return append_frame_bundle(design, body.source_frame_id, body.cells,
                body.length_bp, plane=body.plane, name=body.name)
        return append_independent_bundle(design, body.cells, body.length_bp,
            plane=body.plane, translation_nm=body.translation_nm,
            rotation_xyzw=body.rotation_xyzw, name=body.name)
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error


@router.post('/design/frame-extrusion/validate')
def validate_frame_extrusion(body: FrameExtrusionRequest):
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, detail='No active design')
    if revision != body.expected_revision:
        raise HTTPException(409, detail='Design revision changed')
    candidate = _candidate(design, body)
    return {'status': 'ok', 'revision': revision,
            'added_helices': len(candidate.helices) - len(design.helices),
            'message': ('Existing canonical frame; no end ligation inferred' if body.source_frame_id
                        else 'Independent canonical frame; no end ligation inferred')}


@router.post('/design/frame-extrusion', status_code=201)
def commit_frame_extrusion(body: FrameExtrusionRequest):
    from backend.api.crud import _design_response
    updated, report, entry = state.mutate_with_feature_log(
        op_kind='extrude-frame', label=f'Extrude frame: {len(body.cells)} cells × {body.length_bp} bp',
        params=body.model_dump(mode='json'), fn=lambda design: _candidate(design, body),
        expected_revision=body.expected_revision)
    payload = _design_response(updated, report, preserve_feature_log_id=entry.id)
    payload["vr_transaction"] = {"feature_log_entry_id": entry.id, "target_count": len(body.cells)}
    return payload
