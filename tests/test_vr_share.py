import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.vr_share import router, parse_share_event


def test_share_actions_are_allowlisted_and_survive_event_envelope(tmp_path):
    from backend.api.routes_vr import _event_payload
    path = tmp_path/'events'
    for action in ('pause', 'resume', 'end'):
        event = dict(sequence=3, action=action)
        path.write_text(json.dumps(dict(sequence=4, level_sequence=1, selection_level='base', share_control=event)))
        assert _event_payload({'event_path': str(path)})['share_control'] == event
    for value in (None, {}, dict(sequence=True, action='end'), dict(sequence=1, action='create'), dict(sequence=1, action='start')):
        assert parse_share_event(value) is None


def test_presenter_state_is_local_document_bound_and_atomic(tmp_path, monkeypatch):
    from backend.api import routes_vr as vr, doc_context
    path = tmp_path/'events'
    monkeypatch.setattr(vr, '_require_local', lambda request: None)
    monkeypatch.setattr(vr, '_read_state', lambda: {'doc_id':'test', 'event_path':str(path)})
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'test')
    app=FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        body=dict(active=True,perspective=False,busy=False,failed=False,acknowledged=7)
        assert client.post('/vr/share-controls',json=body).status_code==200
        assert (tmp_path/'events.share').read_text()=='1 0 0 7 0'
        assert not (tmp_path/'events.share.next').exists()
        assert client.post('/vr/share-controls',json={**body,'active':'yes'}).status_code==422
        monkeypatch.setattr(doc_context,'get_current_doc',lambda:'other')
        assert client.post('/vr/share-controls',json=body).status_code==409
        assert (tmp_path/'events.share').read_text()=='1 0 0 7 0'


def test_avatar_mapping_inverts_scale_rotation_translation_and_normalization():
    import numpy as np
    from backend.api.vr_share import presenter_pose
    rotation=np.array([[0,0,1],[0,1,0],[-1,0,0]])
    model=np.eye(4);model[:3,:3]=2*rotation;model[:3,3]=[.1,.2,-.3]
    center=np.array([10.,20.,30.]);offset=np.array([0.,0.,-2.]);scale=.01
    value=dict(presentation=dict(model_to_tracking_rows=model.tolist(),source_center_nm=center.tolist(),
        normalization_model_per_nm=scale,normalized_offset_model=offset.tolist()),head={},hands=[])
    inverse=np.array(presenter_pose(value,rotation)['trackingToSource']).reshape(4,4).T
    source=np.array([4.,7.,12.])
    tracking=model@np.r_[scale*(rotation@source-center)+offset,1]
    assert np.allclose(inverse@tracking,np.r_[source,1])
    small=inverse[:3,:3]
    model[:3,:3]*=2;value['presentation']['model_to_tracking_rows']=model.tolist()
    doubled=np.array(presenter_pose(value,rotation)['trackingToSource']).reshape(4,4).T
    assert np.allclose(doubled[:3,:3],small*.5)


def test_pose_feed_is_fresh_local_and_document_bound(tmp_path, monkeypatch):
    import os, time
    from backend.api import routes_vr as vr, doc_context
    from backend.api.vr_share import router
    event=tmp_path/'events';path=tmp_path/'events.avatar'
    monkeypatch.setattr(vr,'_require_local',lambda request:None)
    monkeypatch.setattr(vr,'_read_state',lambda:{'doc_id':'one','event_path':str(event),'view_rotation':[[1,0,0],[0,1,0],[0,0,1]]})
    monkeypatch.setattr(doc_context,'get_current_doc',lambda:'one')
    payload=dict(enabled=True,tracked=True,presentation=dict(model_to_tracking_rows=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],source_center_nm=[0,0,0],normalization_model_per_nm=1,normalized_offset_model=[0,0,0]),head={'position':[0,1,0],'orientation':[0,0,0,1]},hands=[None,None])
    path.write_text(json.dumps(payload));app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/vr/presenter-pose').json()['avatar']['schema']==1
        ui={'lines': [0.,0.,0.,1.,1.,1.,0.,1.,0.,1.,1.,1.]*200, 'panels': []}
        path.write_text(json.dumps({**payload,'ui':ui}))
        assert client.get('/vr/presenter-pose').json()['avatar']['ui']==ui
        for key in ('enabled','tracked'):
            path.write_text(json.dumps({**payload,key:False}))
            assert client.get('/vr/presenter-pose').json()['avatar'] is None
        path.write_text(json.dumps(payload));os.utime(path,(time.time()-2,time.time()-2))
        assert client.get('/vr/presenter-pose').json()['avatar'] is None
        path.write_text(json.dumps(payload));monkeypatch.setattr(doc_context,'get_current_doc',lambda:'other')
        assert client.get('/vr/presenter-pose').json()['avatar'] is None
