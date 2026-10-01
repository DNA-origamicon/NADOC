"""Local, document-bound presenter controls for an existing desktop share."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.post('/vr/share-controls')
async def share_controls(request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    body = await request.body()
    if len(body) > 1024:
        raise HTTPException(413, detail="Presenter state too large")
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(422, detail="Invalid presenter state")
    if not isinstance(data, dict) or any(type(data.get(k)) is not bool for k in ('active', 'perspective', 'busy', 'failed')) or type(data.get('acknowledged')) is not int or not 0 <= data['acknowledged'] <= 2147483647:
        raise HTTPException(422, detail='Invalid presenter state')
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != get_current_doc():
            raise HTTPException(409, detail='VR belongs to another document or is unavailable')
        path = Path(state['event_path'] + '.share')
        temp = Path(str(path) + '.next')
        temp.write_text(' '.join(str(int(data[k])) for k in ('active', 'perspective', 'busy', 'acknowledged', 'failed')))
        temp.chmod(0o600)
        os.replace(temp, path)
    return {'published': True}


def parse_share_event(value):
    if isinstance(value, dict) and type(value.get('sequence')) is int and 0 < value['sequence'] <= 2147483647 and value.get('action') in ('pause', 'resume', 'end'):
        return {'sequence': value['sequence'], 'action': value['action']}
    return None


def presenter_pose(value, rotation):
    """Invert the exact source-nm -> normalized model -> tracking-metre mapping."""
    import numpy as np
    p = value['presentation']
    model = np.asarray(p['model_to_tracking_rows'], dtype=float)
    r = np.asarray(rotation, dtype=float)
    center = np.asarray(p['source_center_nm'], dtype=float)
    offset = np.asarray(p['normalized_offset_model'], dtype=float)
    scale = float(p['normalization_model_per_nm'])
    if model.shape != (4, 4) or r.shape != (3, 3) or center.shape != (3,) or offset.shape != (3,) or not 0 < scale < 1e9:
        raise ValueError('Invalid normalization')
    normalized = np.eye(4)
    normalized[:3, :3] = scale * r
    normalized[:3, 3] = offset - scale * center
    transform = np.linalg.inv(model @ normalized)
    if not np.isfinite(transform).all():
        raise ValueError('Invalid tracking transform')
    transform[3] = [0, 0, 0, 1]
    return dict(schema=1, trackingToSource=transform.T.ravel().tolist(), head=value['head'], hands=value['hands'], **({'ui': value['ui']} if 'ui' in value else {}))


@router.get('/vr/presenter-pose')
def read_presenter_pose(request: Request):
    import time
    import numpy as np
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    # Desktop sharing polls this optional feed even on hosts without native VR.
    # Keep local access enforcement, but absence of VR is a normal empty pose.
    vr._require_local(request, check_platform=False)
    if vr._native_platform_reason():
        return {'avatar': None}
    state = vr._read_state()
    if not state or state.get('doc_id') != get_current_doc():
        return {'avatar': None}
    try:
        path = Path(state['event_path'] + '.avatar')
        if time.time() - path.stat().st_mtime > 1:
            return {'avatar': None}
        with path.open() as stream:
            value = json.loads(stream.read(4 * 1024 * 1024))
        if not value.get('enabled') or not value.get('tracked'):
            return {'avatar': None}
        return {'avatar': presenter_pose(value, state['view_rotation'])}
    except (OSError, ValueError, KeyError, TypeError, np.linalg.LinAlgError):
        return {'avatar': None}
