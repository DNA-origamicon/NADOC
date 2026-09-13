"""Persistent, engine-independent direct NAMD surface drafts."""
import json
import os
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.core.namd_peg_surface import NamdPegSurface, review_surface

router = APIRouter(prefix='/md/peg-surfaces', tags=['NAMD PEG surfaces'])


def _directory():
    from backend.api.assembly import _WORKSPACE_DIR
    return Path(_WORKSPACE_DIR) / 'namd_surfaces'


def _path(surface_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', surface_id):
        raise HTTPException(422, 'Invalid surface ID')
    return _directory() / f'{surface_id}.json'


@router.post('/review')
def review(body: NamdPegSurface):
    return review_surface(body)


@router.get('')
def list_surfaces():
    records = []
    for path in _directory().glob('*.json'):
        try:
            record = json.loads(path.read_text())
            # Readiness is computed by the current implementation, never trusted from disk.
            records.append({**review_surface(NamdPegSurface.model_validate(record['spec'])),
                            'id': path.stem, 'updated_at': record['updated_at']})
        except (ValueError, KeyError):
            continue
    return sorted(records, key=lambda r: r['updated_at'], reverse=True)


def _save(surface_id, body):
    result = {**review_surface(body), 'id': surface_id,
              'updated_at': datetime.now(timezone.utc).isoformat()}
    path = _path(surface_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    try:
        temp.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return result


@router.post('', status_code=201)
def create_surface(body: NamdPegSurface):
    prefix = re.sub(r'[^a-z0-9_-]+', '-', body.name.lower())[:40]
    return _save(f'{prefix}-{uuid.uuid4().hex[:12]}', body)


@router.put('/{surface_id}')
def update_surface(surface_id: str, body: NamdPegSurface):
    if not _path(surface_id).is_file():
        raise HTTPException(404, 'Surface draft not found')
    return _save(surface_id, body)
