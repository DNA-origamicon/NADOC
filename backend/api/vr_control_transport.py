"""Document-bound control snapshots, delivered outside the async event loop."""
import json
import os
import time
from pathlib import Path
from fastapi import HTTPException
from backend.api.vr_view_transport import send_snapshot


def deliver_control(doc_id, suffix, text):
    from backend.api import routes_vr as vr
    if suffix not in ('.simulations', '.share'):
        raise ValueError('Unsupported control channel')
    started = time.perf_counter()
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get('doc_id') != doc_id:
            raise HTTPException(409, 'VR belongs to another document or is unavailable')
    data = text.encode('utf-8')
    path = Path(state['event_path'] + suffix)
    try:
        transport = 'ipc' if send_snapshot(str(path), data, display=False) else 'file'
        if transport == 'file':
            with vr._FEEDBACK_LOCK:
                current = vr._read_state()
                if not current or current.get('event_path') != state['event_path'] or current.get('doc_id') != doc_id:
                    raise HTTPException(409, 'VR session changed during upload')
                temp = Path(str(path) + '.next')
                temp.write_bytes(data)
                temp.chmod(0o600)
                os.replace(temp, path)
    except OSError as exc:
        raise HTTPException(503, 'VR control transport unavailable') from exc
    if os.environ.get('NADOC_VR_VIEW_PIPELINE') == '1':
        print('VR_CONTROL_PIPELINE '+json.dumps({'channel':suffix,'transport':transport,'bytes':len(data),'ms':(time.perf_counter()-started)*1000}),flush=True)
