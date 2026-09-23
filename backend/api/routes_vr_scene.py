"""Revision-checked publication of canonical topology to an existing VR session."""
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from backend.api import state as design_state
from backend.api.doc_context import get_current_doc

router = APIRouter()

class VRSceneRefreshRequest(BaseModel):
    expected_design_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0, strict=True)


def publish_scene(body):
    from backend.api import routes_vr as vr
    with vr._STATE_LOCK:
        session = vr._read_state()
        if not session or session.get('doc_id') != get_current_doc():
            raise HTTPException(409, detail='VR session belongs to a different document or is unavailable')
        design, revision = design_state.get_design_with_revision()
        if design is None or design.id != body.expected_design_id or revision != body.expected_revision:
            raise HTTPException(409, detail='Design changed before scene refresh')
        request = vr.VRLaunchRequest.model_validate(session['launch_request'])
        source = vr._write_scene_snapshot(producer=lambda write: vr._snapshot(request, line_writer=write))
        manifest = Path(session['event_path'] + '.scene')
        destination = Path(session['event_path'] + f'.scene-{revision}')
        pending = manifest.with_name(manifest.name + '.next')
        try:
            current, current_revision = design_state.get_design_with_revision()
            if current is None or current.id != body.expected_design_id or current_revision != revision:
                raise HTTPException(409, detail='Design changed during scene refresh')
            previous = manifest.read_text().split()[-1] if manifest.exists() else None
            os.replace(source, destination)
            pending.write_text(f'NADOCVR_SCENE 1 {revision} {destination}\n')
            pending.chmod(0o600)
            os.replace(pending, manifest)
            if previous and previous != str(destination):
                old = Path(previous)
                if old.parent == destination.parent and old.name.startswith(Path(session['event_path']).name + '.scene-'):
                    old.unlink(missing_ok=True)
        finally:
            source.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
        return {'published': True, 'scene_revision': revision}


@router.post('/vr/scene-refresh')
def refresh_scene(body: VRSceneRefreshRequest, request: Request):
    from backend.api.routes_vr import _require_local
    _require_local(request)
    return publish_scene(body)


def cleanup_scene_refresh(event_path):
    event = Path(event_path)
    Path(str(event) + '.scene').unlink(missing_ok=True)
    Path(str(event) + '.scene.next').unlink(missing_ok=True)
    for candidate in event.parent.glob(event.name + '.scene-*'):
        if candidate.name.removeprefix(event.name + '.scene-').isdigit():
            candidate.unlink(missing_ok=True)
