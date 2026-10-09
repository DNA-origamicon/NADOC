"""Document-bound small decisions owned by the browser's existing handlers."""
import json
import os
import unicodedata
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from backend.api.vr_routing import parse_event

router = APIRouter()


class Option(BaseModel):
    id: str = Field(pattern=r'^[0-3]$')
    label: str = Field(min_length=1, max_length=96)


class Snapshot(BaseModel):
    version: int = Field(ge=1, le=2147483647)
    heartbeat: int = Field(ge=1, le=2147483647)
    detail_allowed: bool = True
    title: str = Field(max_length=256)
    message: str = Field(max_length=16384)
    options: list[Option] = Field(max_length=4)

    @model_validator(mode='after')
    def unique_options(self):
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError('Option IDs must be unique')
        return self


def encode(snapshot):
    def quoted(value):
        text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
        return json.dumps(' '.join(text.split()))
    lines = [f'NADOC_PROMPT_1 {snapshot.version} {snapshot.heartbeat} {len(snapshot.options)} {int(snapshot.detail_allowed)} '
             f'{quoted(snapshot.title)} {quoted(snapshot.message)}']
    lines.extend(f'{quoted(o.id)} {quoted(o.label)}' for o in snapshot.options)
    return '\n'.join(lines) + '\n'


@router.post('/vr/prompt')
async def publish(body: Snapshot, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != get_current_doc():
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
        path = Path(state['event_path'] + '.prompt')
        temporary = Path(str(path) + '.next')
        temporary.write_text(encode(body))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {'published': True}
