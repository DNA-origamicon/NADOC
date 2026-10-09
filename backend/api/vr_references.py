"""Ephemeral desktop-owned STL bridge. Never touches a design or its history."""
import json
import math
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def validate_references(data):
    if not isinstance(data, dict) or type(data.get('revision')) is not int or not 0 <= data['revision'] <= 2147483647:
        raise ValueError('Invalid revision')
    models = data.get('models')
    if not isinstance(models, list) or len(models) > 64:
        raise ValueError('Maximum 64 reference models')
    ids = set()
    total = 0
    for model in models:
        identity = model.get('id', '')
        if not isinstance(identity, str) or not 1 <= len(identity) <= 64 or not all(c.isalnum() or c == '-' for c in identity) or identity in ids:
            raise ValueError('Invalid reference identity')
        ids.add(identity)
        for key, length in [('matrix', 16), ('color', 3), ('vertices', None)]:
            values = model.get(key)
            if not isinstance(values, list) or (length is not None and len(values) != length) or not all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e15 for v in values):
                raise ValueError('Invalid reference ' + key)
        vertices = model['vertices']; total += len(vertices)
        if not vertices or len(vertices) % 9 or total > 9_000_000:
            raise ValueError('Maximum one million triangles total')
        if any(not 0 <= c <= 1 for c in model['color']) or type(model.get('opacity')) not in (int, float) or not 0 <= model['opacity'] <= 1:
            raise ValueError('Invalid reference appearance')
        # Uniform, invertible affine poses only (picking needs an inverse).
        import numpy as np
        matrix = np.asarray(model['matrix']).reshape(4, 4).T
        gram = matrix[:3, :3].T @ matrix[:3, :3]
        scale = float(gram[0, 0])
        if scale < 1e-18 or not np.allclose(matrix[3], [0, 0, 0, 1]) or not np.allclose(gram, np.eye(3) * scale, rtol=1e-5, atol=1e-12):
            raise ValueError('Reference pose must have uniform nonzero scale')
    if data.get('selected', '') not in ids | {''}:
        raise ValueError('Invalid selected reference')
    return data


def session_state(request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request, check_platform=False)
    state = vr._read_state()
    return state if state and state.get('doc_id') == get_current_doc() and state.get('event_path') else None


@router.get('/vr/references')
def get_references(request: Request):
    state = session_state(request)
    if not state:
        return {'session': None}
    event = None
    try:
        event = json.loads(Path(state['event_path'] + '.references-event').read_text())
    except (OSError, ValueError):
        pass
    return {'session': Path(state['event_path']).name, 'event': event}


@router.post('/vr/references')
async def publish_references(request: Request):
    from backend.api import routes_vr as vr
    state = session_state(request)
    if not state:
        raise HTTPException(409, detail='VR belongs to another document or is unavailable')
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 150 * 1024 * 1024:
            raise HTTPException(413, detail='Reference geometry is too large')
    try:
        data = validate_references(json.loads(chunks))
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        raise HTTPException(422, detail=str(error))
    rotation = state.get('view_rotation', [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    lines = [f"NADOC_REFERENCES 1 {data['revision']} {len(data['models'])}", ' '.join(str(v) for row in rotation for v in row), data.get('selected') or '-']
    for model in data['models']:
        lines.extend([f"{model['id']} {len(model['vertices']) // 3} {model['opacity']}",
                      ' '.join(map(str, model['color'])), ' '.join(map(str, model['matrix'])),
                      ' '.join(map(str, model['vertices']))])
    with vr._FEEDBACK_LOCK:
        if session_state(request) != state:
            raise HTTPException(409, detail='VR session changed')
        path = Path(state['event_path'] + '.references')
        temp = Path(str(path) + '.next')
        temp.write_text('\n'.join(lines)); temp.chmod(0o600); os.replace(temp, path)
    return {'published': True}
