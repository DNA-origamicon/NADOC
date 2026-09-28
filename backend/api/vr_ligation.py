"""Publish browser-resolved ligatable terminals in the launch view frame."""
import os
from pathlib import Path
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

router = APIRouter()


class End(BaseModel):
    role: Literal[3, 5]
    strand: int = Field(ge=0)
    identity: str = Field(min_length=1, max_length=2048, pattern=r'^[A-Za-z0-9%_.!~*\x27()-]+$')
    position: tuple[float, float, float]
    tangent: tuple[float, float, float]
    expanded_offset: tuple[float, float, float] = (0, 0, 0)


class Bond(BaseModel):
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    offset_a: tuple[float, float, float] = (0, 0, 0)
    offset_b: tuple[float, float, float] = (0, 0, 0)


class Catalog(BaseModel):
    version: int = Field(ge=1)
    status: Literal['ready', 'created', 'failed', 'refused'] = 'ready'
    ends: list[End] = Field(max_length=32768)
    bonds: list[Bond] = Field(default_factory=list, max_length=1000000)


def record(body, rotation):
    rotation = np.asarray(rotation, dtype=float)
    if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
        raise HTTPException(422, detail='Invalid VR view rotation')
    lines = [f'NADOC_LIGATION_1 {body.version} {body.status} {len(body.ends)}']
    for end in body.ends:
        values = [*(rotation @ end.position), *(rotation @ end.tangent), *(rotation @ end.expanded_offset)]
        if not np.isfinite(values).all() or np.max(np.abs(values)) > 1e9:
            raise HTTPException(422, detail='Invalid ligation end geometry')
        lines.append(f'{end.role} {end.strand} {end.identity} ' + ' '.join(f'{v:.17g}' for v in values))
    lines.append(f'BONDS {len(body.bonds)}')
    for bond in body.bonds:
        values = [*(rotation @ bond.a), *(rotation @ bond.b), *(rotation @ bond.offset_a), *(rotation @ bond.offset_b)]
        if not np.isfinite(values).all() or np.max(np.abs(values)) > 1e9:
            raise HTTPException(422, detail='Invalid nick bond geometry')
        lines.append(' '.join(f'{v:.17g}' for v in values))
    return '\n'.join(lines) + '\n'


@router.post('/vr/ligation-ends')
def publish(body: Catalog, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    state = vr._read_state()
    if not state or state.get('doc_id') != get_current_doc():
        raise HTTPException(409, detail='Native VR is unavailable or belongs to another document')
    data = record(body, state.get('view_rotation'))
    path = Path(state['event_path'] + '.ligation')
    temporary = path.with_name(path.name + '.next')
    with vr._FEEDBACK_LOCK:
        temporary.write_text(data)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {'published': True}


def parse_event(value):
    if not isinstance(value, dict) or any(type(value.get(k)) is not int for k in ('sequence', 'version', 'source', 'target')):
        return None
    action = value.get('action', 'ligate')
    if action not in ('ligate', 'nick', 'undo', 'redo'):
        return None
    if value['sequence'] < 1 or value['version'] < 1 or not all(0 <= value[k] < (1000000 if action == 'nick' else 32768) for k in ('source', 'target')):
        return None
    return {**{k: value[k] for k in ('sequence', 'version', 'source', 'target')}, **({'action': action} if 'action' in value else {})}
