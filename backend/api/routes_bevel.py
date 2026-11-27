"""Source-bound Bevel preview, creation and editable native history."""
from contextvars import copy_context
from uuid import uuid4
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException
from pydantic import Field, StrictInt

from backend.api import state
from backend.api.part_bevel_commands import BevelCommand, BevelRequest, bevel_guide, build

router = APIRouter()
_preview_slots = BoundedSemaphore(2)


class CreateBevelRequest(BevelRequest):
    expected_design_id: str = Field(min_length=1, max_length=256)
    expected_revision: StrictInt = Field(ge=0)
    preview_token: str | None = Field(default=None, min_length=32, max_length=32)


def feature_index(source, feature_id):
    for index, entry in enumerate(source.feature_log):
        if entry.id == feature_id and getattr(entry, 'op_kind', None) == 'bevel':
            BevelCommand.model_validate(entry.params)
            return index
    raise HTTPException(409, detail='The Bevel feature changed. Reopen its editor.')


def inputs(body):
    return {key: getattr(body, key) for key in BevelRequest.model_fields}


@router.post('/design/bevel/preview')
def preview_bevel(body: CreateBevelRequest, feature_id: str | None = None):
    from backend.api.bevel_prepared import capture, retain
    from backend.api.corner_projection_worker import project_corner_in_worker
    from backend.api.feature_recording import record_feature
    from backend.api.part_recipe_edit import prepare_change
    source, owner = capture(body)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail='Return to the latest history position before creating a Bevel.')
    def evaluate():
        guide = None
        if feature_id is None:
            command = BevelCommand(**inputs(body), operation_id=uuid4().hex)
            params = command.model_dump(mode='json', by_alias=True)
            guide = bevel_guide(source, command)
            candidate, validation, entry = record_feature(state._DesignSession(design=source),
                'bevel', f'Bevel: {body.angle_deg:g}° at {body.position_bp} bp',
                params, lambda design: build(design, params))
            identity = entry.id
        else:
            index = feature_index(source, feature_id)
            def bind(kind, params, prefix):
                nonlocal guide
                guide = bevel_guide(prefix, body)
                return params
            candidate, validation = prepare_change(source, source, index, lambda: None,
                params=inputs(body), input_binder=bind)
            identity = feature_id
        component = project_corner_in_worker(candidate)
        packet = dict(candidate=component, feature_id=identity, _validation=validation)
        token = retain(owner, body, feature_id, candidate, packet)
        return dict(candidate=component, guide=guide, preview_token=token)
    # A superseded browser request may still be finishing its projection.
    # Queue briefly rather than rejecting the user's next parameter change.
    if not _preview_slots.acquire(timeout=30):
        raise HTTPException(503, detail='Bevel preview is busy. Try again shortly.')
    try:
        return copy_context().run(evaluate)
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    finally:
        _preview_slots.release()


@router.post('/design/bevel', status_code=201)
def create_bevel(body: CreateBevelRequest):
    if body.preview_token:
        from backend.api.bevel_prepared import commit
        return commit(body)
    from backend.api.crud import _design_response_with_geometry
    params = BevelCommand(**inputs(body), operation_id=uuid4().hex).model_dump(mode='json', by_alias=True)
    def regenerate(source):
        if source.id != body.expected_design_id:
            raise HTTPException(409, detail='Active design changed.')
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(409, detail='Return to the latest history position before creating a Bevel.')
        try:
            return build(source, params)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
    updated, validation, entry = state.mutate_with_feature_log(op_kind='bevel',
        label=f'Bevel: {body.angle_deg:g}° at {body.position_bp} bp', params=params,
        fn=regenerate, expected_revision=body.expected_revision)
    return _design_response_with_geometry(updated, validation,
        preserve_feature_log_id=entry.id, normalize_legacy=False)


@router.patch('/design/bevel/{feature_id}')
def edit_bevel(feature_id: str, body: CreateBevelRequest):
    if body.preview_token:
        from backend.api.bevel_prepared import commit
        return commit(body, feature_id)
    from backend.api.part_recipe_edit import change_recipe
    source, revision = state.copy_for_persist()
    if source is None or source.id != body.expected_design_id or revision != body.expected_revision:
        raise HTTPException(409, detail='The Bevel source changed. Reopen its editor.')
    return change_recipe(feature_index(source, feature_id), params=inputs(body),
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=feature_id, complete_geometry=True)
