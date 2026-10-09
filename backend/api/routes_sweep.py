"""Headless and UI sweep transactions share the same builder and preview."""
from fastapi import APIRouter, HTTPException
from backend.api import state
from backend.core.sweep import SweepRequest, build_sweep, sweep_preview, sweep_mutation_report

router = APIRouter()


def _guard(design, body):
    if body.expected_design_id is not None and design.id != body.expected_design_id:
        raise HTTPException(409, detail='Active design changed')


@router.post('/design/sweep/preview')
def preview_sweep(body: SweepRequest, feature_index: int | None = None, include_geometry: bool = True):
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, detail='No active design')
    _guard(design, body)
    if body.expected_revision is not None and body.expected_revision != revision:
        raise HTTPException(409, detail='Design revision changed')
    try:
        if feature_index is None:
            result, _ = sweep_preview(design, body, include_geometry=include_geometry)
        else:
            from backend.api.sweep_history import preview_sweep_edit
            result = preview_sweep_edit(design, body, feature_index)
        return {**result, 'revision': revision}
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post('/design/sweep', status_code=201)
def create_sweep(body: SweepRequest):
    from backend.api.crud import _design_response_with_geometry
    changed_helix_ids = None
    def build(design):
        nonlocal changed_helix_ids
        _guard(design, body)
        try:
            result = build_sweep(design, body)
            # A detached sweep leaves authored material untouched. Reuse the
            # desktop partial-geometry merge, including axes for the new helices.
            # Continuations / ligations that alter old strands retain a full
            # response, so terminal flags, ownership and junctions stay correct.
            surviving = {strand.id: strand for strand in result.strands}
            if not body.source_helix_id and all(surviving.get(s.id) == s for s in design.strands):
                old_ids = {h.id for h in design.helices}
                changed_helix_ids = [h.id for h in result.helices if h.id not in old_ids]
            return result, sweep_mutation_report(design, result, body)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
    updated, report, entry = state.mutate_with_feature_log(
        op_kind='sweep', label=f'Sweep: {len(body.cells)} cells · {len(body.points_nm)} points',
        params=body.model_dump(mode='json'), fn=build, expected_revision=body.expected_revision)
    payload = _design_response_with_geometry(updated, report,
        changed_helix_ids=changed_helix_ids, partial_axes=True,
        preserve_feature_log_id=entry.id)
    payload['vr_transaction'] = {'feature_log_entry_id': entry.id, 'target_count': len(body.cells)}
    return payload
