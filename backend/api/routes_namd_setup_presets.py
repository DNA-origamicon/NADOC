"""Workspace-wide NAMD sidebar presets; never launch or mutate simulation jobs."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix='/md/setup-presets', tags=['NAMD setup presets'])
_lock = threading.Lock()


class SetupPreset(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    settings: dict
    revision: int | None = None

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Enter a preset name')
        return value

    @field_validator('settings')
    @classmethod
    def valid_settings(cls, value):
        if value.get('schema') != 'nadoc.namd_setup.v1':
            raise ValueError('Unsupported setup preset schema')
        if len(json.dumps(value, allow_nan=False)) > 262144:
            raise ValueError('Setup preset is too large')
        return value


def directory():
    from backend.api.assembly import _WORKSPACE_DIR
    return Path(_WORKSPACE_DIR) / 'namd_setup_presets'


def preset_path(preset_id):
    try:
        parsed = uuid.UUID(preset_id)
    except ValueError:
        raise HTTPException(422, 'Invalid preset ID') from None
    return directory() / f'{parsed.hex}.json'


def read_record(path):
    if not path.is_file():
        raise HTTPException(404, 'Setup preset not found')
    return json.loads(path.read_text())


@router.get('')
def list_presets():
    return sorted((json.loads(p.read_text()) for p in directory().glob('*.json')),
                  key=lambda r: r['name'].casefold())


def write_record(preset_id, body, existing=None):
    if any(r['name'].casefold() == body.name.casefold() and r['id'] != preset_id
           for r in list_presets()):
        raise HTTPException(409, 'A preset already has that name. Select it and use Overwrite.')
    record = {'id': preset_id, 'name': body.name, 'settings': body.settings,
              'revision': existing['revision'] + 1 if existing else 1,
              'updated_at': datetime.now(timezone.utc).isoformat()}
    path = preset_path(preset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    try:
        temp.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return record


@router.post('', status_code=201)
def create_preset(body: SetupPreset):
    with _lock:
        return write_record(uuid.uuid4().hex, body)


@router.put('/{preset_id}')
def overwrite_preset(preset_id: str, body: SetupPreset):
    with _lock:
        existing = read_record(preset_path(preset_id))
        if body.revision != existing['revision']:
            raise HTTPException(409, 'Preset changed elsewhere. Reload the preset list before overwriting.')
        return write_record(existing['id'], body, existing)


@router.delete('/{preset_id}')
def delete_preset(preset_id: str, revision: int):
    with _lock:
        path = preset_path(preset_id)
        existing = read_record(path)
        if revision != existing['revision']:
            raise HTTPException(409, 'Preset changed elsewhere. Reload before deleting.')
        path.unlink()
        return {'deleted': existing['id']}
