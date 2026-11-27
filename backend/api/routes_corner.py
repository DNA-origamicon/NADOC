"""Corner authoring transaction. Preview ownership is handled separately."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import Field, StrictInt

from backend.api import state
from backend.api.part_corner_commands import CornerCommand, CornerRequest, build


router = APIRouter()


class CreateCornerRequest(CornerRequest):
    expected_design_id: str = Field(min_length=1, max_length=256)
    expected_revision: StrictInt = Field(ge=0)
    preview_token: str | None = Field(default=None, min_length=32, max_length=32)


@router.post('/design/corner/preview')
def preview_corner(body: CreateCornerRequest, feature_id: str | None = None):
    from backend.api.corner_preview_stream import corner_preview_response
    from backend.api.corner_prepared import capture
    source, owner = capture(body)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail='Return to the latest history position before creating a Corner.')
    if feature_id is not None:
        from backend.api.corner_history import corner_feature_index
        corner_feature_index(source, feature_id)
    return corner_preview_response(source, body, feature_id=feature_id, owner=owner)


@router.patch('/design/corner/{feature_id}')
def edit_corner(feature_id: str, body: CreateCornerRequest):
    if body.preview_token is not None:
        from backend.api.corner_prepared import commit
        return commit(body, feature_id)
    from backend.api.corner_history import corner_feature_index
    from backend.api.part_recipe_edit import change_recipe
    source, revision = state.copy_for_persist()
    if source is None or source.id != body.expected_design_id or revision != body.expected_revision:
        raise HTTPException(409, detail='The Corner source changed. Reopen its editor.')
    index = corner_feature_index(source, feature_id)
    return change_recipe(index, params={key: getattr(body, key) for key in CornerRequest.model_fields},
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=feature_id, complete_geometry=True)


@router.post('/design/corner', status_code=201)
def create_corner(body: CreateCornerRequest):
    if body.preview_token is not None:
        from backend.api.corner_prepared import commit
        return commit(body)
    from backend.api.crud import _design_response_with_geometry

    command = CornerCommand(**{key: getattr(body, key) for key in CornerRequest.model_fields},
                            operation_id=uuid.uuid4().hex)
    params = command.model_dump(mode='json', by_alias=True)

    def regenerate(source):
        if source.id != body.expected_design_id:
            raise HTTPException(409, detail='Active design changed.')
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(409, detail='Return to the latest history position before creating a Corner.')
        try:
            return build(source, params)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    updated, validation, entry = state.mutate_with_feature_log(
        op_kind='corner', label=f'Corner: {body.angle_deg:g}° at {body.position_bp} bp',
        params=params, fn=regenerate, expected_revision=body.expected_revision)
    response = _design_response_with_geometry(updated, validation,
        preserve_feature_log_id=entry.id, normalize_legacy=False)
    response['corner'] = {'feature_id': entry.id, 'junction_review_required': True}
    return response
