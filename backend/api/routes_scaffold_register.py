"""Experimental circular scaffold register sweep and undoable symbolic start."""
from time import perf_counter
import hashlib
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.api import state
from backend.api.crud import _design_response_with_geometry
from backend.core.scaffold_register import Conditions, evaluate_design, apply_nick

router = APIRouter()


class SweepRequest(BaseModel):
    temperature_c: float = Field(default=50, ge=0, le=100, allow_inf_nan=False)
    scaffold_nM: float = Field(default=10, gt=0, allow_inf_nan=False)
    staple_nM: float = Field(default=100, gt=0, allow_inf_nan=False)
    magnesium_mM: float = Field(default=12.5, ge=0, allow_inf_nan=False)
    tris_mM: float = Field(default=40, ge=0, allow_inf_nan=False)


class ApplyRequest(SweepRequest):
    cut_index: int = Field(ge=0, strict=True)
    expected_revision: int = Field(ge=0)
    design_id: str
    source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


def fingerprint(design):
    """Exclude view/annotation/history updates that can race a read-only sweep."""
    payload = design.model_dump(mode='json', include={
        'id', 'strands', 'helices', 'crossovers', 'forced_ligations', 'overhangs',
    })
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@router.post('/design/scaffold-register/sweep')
def sweep(body: SweepRequest = SweepRequest()):
    started = perf_counter()
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, detail='Open a routed design first.')
    try:
        result = evaluate_design(design, Conditions(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {**result, 'revision': revision, 'design_id': design.id,
            'source_fingerprint': fingerprint(design),
            'elapsed_seconds': perf_counter() - started}


@router.post('/design/scaffold-register/apply')
def apply(body: ApplyRequest):
    def change(design):
        if design.id != body.design_id:
            raise HTTPException(409, detail='The open design changed. Run the sweep again.')
        if fingerprint(design) != body.source_fingerprint:
            raise HTTPException(409, detail='Scaffold, staple or routing data changed. Run the sweep again.')
        return apply_nick(design, body.cut_index)
    try:
        Conditions(**body.model_dump(include=set(SweepRequest.model_fields)))
        updated, report, _ = state.mutate_with_feature_log(
            op_kind='nick', label='Optimize scaffold sequence start (circular)',
            params=body.model_dump(), fn=change,
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _design_response_with_geometry(updated, report)
