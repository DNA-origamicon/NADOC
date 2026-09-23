"""Shared framed-cell mutation adapter; route registration remains in crud."""
from fastapi import HTTPException
from backend.api import state as design_state
from backend.core.lattice_frames import append_frame_cell


def add_frame_cell(body):
    from backend.api.crud import _design_response
    try:
        candidate, helix = append_frame_cell(design_state.get_or_404(), body.lattice_frame_id,
            body.row, body.col, length_bp=body.length_bp, populate_strands=body.populate_strands)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error

    def apply(design):
        design.helices = candidate.helices
        design.strands = candidate.strands
        design.cluster_transforms = candidate.cluster_transforms

    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-add-at-cell', label=f'Add helix at ({body.row}, {body.col})',
        params={**body.model_dump(mode='json'), '_helix_id':helix.id}, fn=apply)
    return _design_response(design, report)
