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
