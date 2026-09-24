from pathlib import Path
import gzip
import pytest
from fastapi import HTTPException
from backend.api import routes_vr as vr, state
from backend.api.doc_context import get_current_doc
from backend.api.routes_vr_scene import VRSceneRefreshRequest, publish_scene, cleanup_scene_refresh
from backend.core.models import Design


def setup(monkeypatch,tmp_path):
    state.set_design(Design())
    session={'doc_id':get_current_doc(),'event_path':str(tmp_path/'event.json'),'launch_request':{}}
    monkeypatch.setattr(vr,'_read_state',lambda:session)
    body=VRSceneRefreshRequest(expected_design_id=state.get_or_404().id,expected_revision=state.revision())
    return session,body


def test_publish_empty_and_cleanup(monkeypatch,tmp_path):
    session,body=setup(monkeypatch,tmp_path)
    result=publish_scene(body)
    assert result=={'published':True,'scene_revision':body.expected_revision}
    manifest=Path(session['event_path']+'.scene')
    text=manifest.read_text().split()
    assert text[:3]==['NADOCVR_SCENE','1',str(body.expected_revision)]
    assert 'Q empty_authoring' in gzip.open(text[3], 'rt').read()
    assert Path(text[3]).stat().st_mode & 0o777==0o600
    cleanup_scene_refresh(session['event_path'])
    assert not manifest.exists() and not Path(text[3]).exists()


@pytest.mark.parametrize('wrong',['document','revision','design'])
def test_wrong_owner_or_stale_revision_does_not_publish(monkeypatch,tmp_path,wrong):
    session,body=setup(monkeypatch,tmp_path)
    if wrong=='document':session['doc_id']='other'
    elif wrong=='revision':body.expected_revision+=1
    else:body.expected_design_id='other'
    with pytest.raises(HTTPException) as error:publish_scene(body)
    assert error.value.status_code==409
    assert not list(tmp_path.iterdir())


def test_concurrent_edit_during_snapshot_retains_prior_scene(monkeypatch,tmp_path):
    session,body=setup(monkeypatch,tmp_path)
    publish_scene(body)
    manifest=Path(session['event_path']+'.scene');before=manifest.read_text()
    snapshot=vr._snapshot
    def changed(*args,**kwargs):
        result=snapshot(*args,**kwargs)
        state.set_design(Design())
        return result
    monkeypatch.setattr(vr,'_snapshot',changed)
    with pytest.raises(HTTPException):publish_scene(body)
    assert manifest.read_text()==before
    cleanup_scene_refresh(session['event_path'])
