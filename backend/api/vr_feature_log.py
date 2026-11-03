"""Versioned, document-bound feature-history view for the native VR rail."""
import json
import os
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class Row(BaseModel):
    id: str = Field(pattern=r'^r:[0-9]+$', max_length=32)
    label: str = Field(max_length=4096)
    enabled: bool = True
    active: bool = False
    edit: bool = False
    revert: bool = False
    delete: bool = False
    expand: bool = False


class Target(BaseModel):
    id: str = Field(pattern=r'^t:[0-9]+$', max_length=32)
    label: str = Field(max_length=4096)
    enabled: bool
    active: bool


class Snapshot(BaseModel):
    version: int = Field(ge=1, le=2147483647)
    acknowledged: int = Field(ge=0, le=2147483647)
    title: str = Field(max_length=4096)
    status: str = Field(default='', max_length=8192)
    busy: bool = False
    rows: list[Row] = Field(max_length=10000)
    targets: list[Target] = Field(max_length=10000)


def encode(snapshot):
    def q(value):
        text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
        return json.dumps(' '.join(text.split())[:250])
    lines = [f'NADOC_FEATURE_LOG_1 {snapshot.version} {snapshot.acknowledged} '
             f'{int(snapshot.busy)} {len(snapshot.rows)} {len(snapshot.targets)} '
             f'{q(snapshot.title)} {q(snapshot.status)}']
    for row in snapshot.rows:
        flags = ' '.join(str(int(getattr(row, key))) for key in ('enabled', 'active', 'edit', 'revert', 'delete', 'expand'))
        lines.append(f'{q(row.id)} {q(row.label)} {flags}')
    for target in snapshot.targets:
        lines.append(f'{q(target.id)} {q(target.label)} {int(target.enabled)} {int(target.active)}')
    return '\n'.join(lines) + '\n'


@router.post('/vr/feature-log')
async def publish(body: Snapshot, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != get_current_doc():
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
        path = Path(state['event_path'] + '.feature-log')
        temporary = Path(str(path) + '.next')
        temporary.write_text(encode(body))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {'published': True}


def parse_event(value):
    if not isinstance(value, dict):
        return None
    if any(type(value.get(k)) is not int or not 1 <= value[k] <= 2147483647 for k in ('sequence', 'version')):
        return None
    if not isinstance(value.get('id'), str) or not re.fullmatch(r'(?:[rt]:[0-9]{1,5}|a:[0-9]{1,5}:(?:edit|revert|delete|expand))', value['id']):
        return None
    return {key: value[key] for key in ('sequence', 'version', 'id')}


class SweepEditRequest(BaseModel):
    index: int = Field(ge=0, le=99999)
    feature_id: str = Field(min_length=1, max_length=256)
    expected_design_id: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(ge=0)


@router.post('/vr/sweep-edit')
def open_sweep_edit(body: SweepEditRequest, request: Request):
    """Resolve saved parameters and placement before asking the native editor to open."""
    from backend.api import routes_vr as vr, state
    from backend.api.doc_context import get_current_doc
    from backend.api.routes_sweep import preview_sweep
    from backend.core.sweep import SweepRequest
    from backend.core.vr_sweep_draft import validate_sweep_draft
    import time

    vr._require_local(request)
    design, revision = state.get_design_with_revision()
    if (design is None or design.id != body.expected_design_id or revision != body.expected_revision
            or body.index >= len(design.feature_log) or design.feature_log[body.index].id != body.feature_id):
        raise HTTPException(409, 'Sweep feature changed; reopen the Feature Log')
    entry = design.feature_log[body.index]
    if getattr(entry, 'op_kind', None) != 'sweep':
        raise HTTPException(422, 'Select a Sweep feature')
    params = SweepRequest.model_validate({**entry.params, 'expected_design_id': design.id, 'expected_revision': revision})
    draft = dict(target_kind='none', painted_footprint=dict(lattice_type=design.lattice_type.value, cells=params.cells),
                 points_nm=params.points_nm, orientations_deg=params.orientations_deg, extrude_from=params.plane,
                 strand_filter=params.strand_filter, ligate_adjacent=params.ligate_adjacent)
    # Native editing has explicit bounded geometry limits; never silently truncate.
    draft = json.loads(json.dumps(draft))
    try:
        validate_sweep_draft(draft)
    except ValueError as exc:
        raise HTTPException(422, 'This Sweep exceeds the native editor limits') from exc
    preview = preview_sweep(params, feature_index=body.index)
    rotation = preview['point_rotation']
    origin = preview['origin_nm']
    # The native editor keeps authored coordinates; this maps them to the saved placement.
    import numpy as np
    basis = (np.asarray(rotation).T @ np.asarray(preview['orientation_basis'])).tolist()
    serial = time.time_ns()
    values = [f'NADOC_SWEEP_EDIT_1 {serial} {body.index} {revision} {json.dumps(entry.id)} {json.dumps(design.id)}',
              f'{params.plane} {int(design.lattice_type.value == "SQUARE")} {params.strand_filter} {int(params.ligate_adjacent)}',
              ' '.join(map(str, origin + [v for row in rotation for v in row] + [v for row in basis for v in row])),
              f'{len(params.cells)} {len(params.points_nm)}']
    values.extend(f'{r} {c}' for r, c in params.cells)
    orientations = params.orientations_deg or [None] * len(params.points_nm)
    values.extend(' '.join(map(str, [*point, int(angles is not None), *(angles or [0, 0, 0])]))
                  for point, angles in zip(params.points_nm, orientations))
    with vr._FEEDBACK_LOCK:
        session = vr._read_state()
        if not session or session.get('doc_id') != get_current_doc():
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
        if state.get_design_with_revision()[1] != revision:
            raise HTTPException(409, 'Design changed while opening the Sweep')
        path = Path(session['event_path'] + '.sweep-edit')
        temporary = Path(str(path) + '.next')
        temporary.write_text('\n'.join(values) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {'published': True}
