"""Source-bound Bevel preview, creation and editable native history."""
from contextvars import copy_context
from uuid import uuid4
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request, Query, Path
from fastapi.responses import ORJSONResponse
from pydantic import Field, StrictInt

from backend.api import state
from backend.api.part_bevel_commands import BevelCommand, BevelRequest, build

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
async def preview_bevel_http(body: CreateBevelRequest, request: Request,
                             feature_id: str | None = None, prepare_only: bool = False,
                             preparation_id: str | None = Query(default=None, pattern=r'^[0-9a-f]{32}$')):
    from backend.api.bevel_preparation import prepare_until_disconnected
    result = await prepare_until_disconnected(request, lambda check: preview_bevel(
        body, feature_id, prepare_only, check_cancel=check), preparation_id)
    return ORJSONResponse(result)


@router.post('/design/bevel/preparations/{preparation_id}/cancel')
def cancel_bevel_preparation(preparation_id: str = Path(pattern=r'^[0-9a-f]{32}$')):
    from backend.api.bevel_preparation import cancel_preparation
    cancel_preparation(preparation_id)
    return {'cancelled': True}


def preview_bevel(body: CreateBevelRequest, feature_id: str | None = None,
                  prepare_only: bool = False, *, check_cancel=lambda *_: None):
    from backend.api.bevel_prepared import capture, retain
    from backend.api.corner_projection_worker import project_corner_in_worker
    from backend.api.feature_recording import record_feature
    from backend.api.part_recipe_edit import prepare_change
    source, owner = capture(body)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail='Return to the latest history position before creating a Bevel.')
    def evaluate():
        check_cancel()
        guide = None
        if feature_id is None:
            command = BevelCommand(**inputs(body), operation_id=uuid4().hex)
            params = command.model_dump(mode='json', by_alias=True)
            guide = _guide(source, command)
            candidate, validation, entry = record_feature(state._DesignSession(design=source),
                'bevel', f'Bevel: {body.angle_deg:g}° at {body.position_bp} bp',
                params, lambda design: build(design, params))
            identity = entry.id
        else:
            index = feature_index(source, feature_id)
            def bind(kind, params, prefix):
                nonlocal guide
                guide = _guide(prefix, body)
                return params
            candidate, validation = prepare_change(source, source, index, lambda: None,
                params=inputs(body), input_binder=bind)
            identity = feature_id
        check_cancel()
        component = project_corner_in_worker(candidate, on_progress=check_cancel)
        check_cancel()
        packet = dict(candidate=component, feature_id=identity, _validation=validation)
        token = retain(owner, body, feature_id, candidate, packet)
        # The live planar preview is already local. Preparing Apply needs only
        # its token; do not serialize/send the large Full payload twice.
        if prepare_only:
            return dict(guide=guide, preview_token=token)
        return dict(candidate=component, guide=guide, preview_token=token)
    # Stay cancellable while the preceding request reaps its projection workers.
    from time import monotonic
    deadline = monotonic() + 30
    while not _preview_slots.acquire(timeout=.05):
        check_cancel()
        if monotonic() >= deadline:
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
        return ORJSONResponse(commit(body), status_code=201)
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
    return ORJSONResponse(_design_response_with_geometry(updated, validation,
        preserve_feature_log_id=entry.id, normalize_legacy=False, compact_deformed=True), status_code=201)


@router.patch('/design/bevel/{feature_id}')
def edit_bevel(feature_id: str, body: CreateBevelRequest):
    if body.preview_token:
        from backend.api.bevel_prepared import commit
        return ORJSONResponse(commit(body, feature_id))
    from backend.api.part_recipe_edit import change_recipe
    source, revision = state.copy_for_persist()
    if source is None or source.id != body.expected_design_id or revision != body.expected_revision:
        raise HTTPException(409, detail='The Bevel source changed. Reopen its editor.')
    return ORJSONResponse(change_recipe(feature_index(source, feature_id), params=inputs(body),
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=feature_id, complete_geometry=True, compact_geometry=True))


def _guide(design, request):
    from backend.api.bevel_live import source_axes, plane
    center, normal = plane(source_axes(design, request.cluster_id), request)
    return dict(center_nm=center.tolist(), plane_normal=normal.tolist(), cuts=[])


@router.post('/design/bevel/source')
def bevel_source(body: CreateBevelRequest, feature_id: str | None = None, include_geometry: bool = True,
                 compact_geometry: bool = False):
    from backend.api.bevel_prepared import capture
    from backend.api.bevel_live import source_axes
    from backend.api.corner_projection_worker import project_corner_in_worker
    source, _ = capture(body)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail='Return to the latest history position before creating a Bevel.')
    if not _preview_slots.acquire(timeout=30):
        raise HTTPException(503, detail='Bevel preview is busy. Try again shortly.')
    try:
        if feature_id:
            from backend.api.bevel_edit_source import replay_source
            source = replay_source(source, feature_index(source, feature_id))
        paths = source_axes(source, body.cluster_id)
        compact = compact_geometry and not any(s.is_reference for s in source.strands)
        from backend.api.bevel_live import cached_display
        component = cached_display(source) if compact and (include_geometry or feature_id) else None
        if component is None and (include_geometry or feature_id):
            component = project_corner_in_worker(source, include_straight=False)
        if component is not None and compact and 'nucleotides' in component:
            from backend.core.design_geometry import _compact_geometry_from_nucleotides
            component['nucleotides_compact'] = _compact_geometry_from_nucleotides(component.pop('nucleotides'))
        return ORJSONResponse(dict(paths=paths, component=component))
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    finally:
        _preview_slots.release()
