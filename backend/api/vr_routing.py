"""Document-bound desktop routing controls for the native sidebar."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class Control(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9:_-]+$', max_length=100)
    label: str = Field(max_length=4096)
    detail: str = Field(default='', max_length=8192)
    enabled: bool
    active: bool


class Snapshot(BaseModel):
    version: int = Field(ge=1, le=2147483647)
    acknowledged: int = Field(ge=0, le=2147483647)
    title: str = Field(max_length=4096)
    roots: list[Control] = Field(max_length=20)
    controls: list[Control] = Field(max_length=1000)


def encode(snapshot):
    def quoted(value):
        # Native stroke font is ASCII; preserve readable approximations.
        import unicodedata
        text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
        return json.dumps(' '.join(text.split())[:250])
    lines = [f'NADOC_ROUTING_1 {snapshot.version} {snapshot.acknowledged} {len(snapshot.roots)} {len(snapshot.controls)} {quoted(snapshot.title)}']
    for row in [*snapshot.roots, *snapshot.controls]:
        lines.append(f'{quoted(row.id)} {quoted(row.label)} {quoted(row.detail)} {int(row.enabled)} {int(row.active)}')
    return '\n'.join(lines) + '\n'


@router.post('/vr/routing')
async def publish(body: Snapshot, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != get_current_doc():
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
        path = Path(state['event_path'] + '.routing')
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
    import re
    if not isinstance(value.get('id'), str) or not re.fullmatch(r'[a-z0-9:_-]{1,96}', value['id']):
        return None
    return {k: value[k] for k in ('sequence', 'version', 'id')}
