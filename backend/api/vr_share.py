"""Local, document-bound presenter controls for the presentation lifecycle."""
import json
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.concurrency import run_in_threadpool
from backend.api.vr_control_transport import deliver_control

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
    if type(data.get('perspectiveAvailable', True)) is not bool or type(data.get('startAvailable', False)) is not bool or type(data.get('headsetPerspective', False)) is not bool:
        raise HTTPException(422, detail='Invalid presenter availability')
    if any(type(data.get(k, 0)) is not int or not 0 <= data.get(k, 0) <= 10000 for k in ('activeGuests', 'waitingGuests')):
        raise HTTPException(422, detail='Invalid guest counts')
    await run_in_threadpool(deliver_control, get_current_doc(), '.share', ' '.join(str(int(data[k])) for k in ('active', 'perspective', 'busy', 'acknowledged', 'failed')) + f" {data.get('activeGuests', 0)} {data.get('waitingGuests', 0)} {int(data.get('perspectiveAvailable', True))} {int(data.get('startAvailable', False))} {int(data.get('headsetPerspective', False))}")
    return {'published': True}


def parse_share_event(value):
    if isinstance(value, dict) and type(value.get('sequence')) is int and 0 < value['sequence'] <= 2147483647 and value.get('action') in ('start', 'pause', 'resume', 'end', 'admit'):
        return {'sequence': value['sequence'], 'action': value['action']}
    return None


def presenter_pose(value, rotation, *, include_ui=True):
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
    return dict(schema=1, trackingToSource=transform.T.ravel().tolist(), head=value['head'], hands=value['hands'], **({'ui': value['ui']} if include_ui and 'ui' in value else {}))


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
        if request.query_params.get('preview') == '1':
            preview = value.get('sweepPreview')
            if not value.get('tracked') or not value.get('presenting') or not preview:
                return {'preview': None}
            return {'preview': {**preview, 'trackingToSource': presenter_pose(value, state['view_rotation'], include_ui=False)['trackingToSource']}}
        if not value.get('tracked') or not (value.get('enabled') or (request.query_params.get('camera') == '1' and value.get('presenting'))):
            return {'avatar': None}
        return {'avatar': presenter_pose(value, state['view_rotation'], include_ui=request.query_params.get('camera') != '1')}
    except (OSError, ValueError, KeyError, TypeError, np.linalg.LinAlgError):
        return {'avatar': None}
