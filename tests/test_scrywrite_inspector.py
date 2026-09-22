import json
import struct
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from tools.scrywrite_inspector.service import Inspector, target_details
from tools.scrywrite_inspector.__main__ import make_handler
from tools.vr_motion.session import LiveSession


def test_target_metadata_does_not_claim_inactive_hand_hits():
    state={'menu':'tools','controls':[{'label':'EXTRUDE','position':[0,0,-1],
        'hit_half_right':[.1,0,0],'hit_half_up':[0,.1,0]}], 'hands':[{}, {'valid':False}]}
    target=target_details(state)[0]
    assert target['key']=='tools:EXTRUDE' and 'ray_metrics' not in target


def test_pick_uses_top_down_image_bottom_up_ids_and_preserves_identity(tmp_path):
    service=Inspector('/tmp/fake.sock',tmp_path/'path',tmp_path/'out')
    d=service.output/'capture-1';d.mkdir()
    service.history=[{'name':'capture-1'}]
    (d/'evidence.json').write_text(json.dumps({'state':{'frame':12,'session':'1-2'},'eyes':[{'eye':'left','width':2,'height':2}]}))
    (d/'left.ids.u32').write_bytes(struct.pack('=4I',0,0,42,0))
    (d/'left.classes.u8').write_bytes(bytes([0,0,1,0]))
    (d/'objects.json').write_text(json.dumps([{'id':42,'identity':'helix:test','owner_tokens':['owner']}]))
    value=service.pick('capture-1','left',.1,.1)
    assert value['object']['identity']=='helix:test' and value['render_class']==1
    assert service.pick('capture-1','left',.1,.9)['object'] is None
    for x in (float('nan'),1,-1,True):
        with pytest.raises(ValueError):service.pick('capture-1','left',x,0)


def test_busy_inspector_never_injects_a_second_writer(tmp_path):
    service=Inspector('/tmp/fake.sock',tmp_path/'path',tmp_path/'out')
    with service.lock:
        with pytest.raises(RuntimeError,match='busy'):service.start()
        with pytest.raises(RuntimeError,match='owns'):service.capture()


def test_http_mutations_require_token_and_same_origin(tmp_path):
    service=Inspector('/tmp/fake.sock',tmp_path/'path',tmp_path/'out')
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(service,0,'secret'))
    server.RequestHandlerClass=make_handler(service,server.server_port,'secret')
    thread=threading.Thread(target=server.serve_forever);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(url+'/') as r:assert b'VR inspector' in r.read()
        (service.output/'evidence.json').write_text('{"state":{"frame":12}}')
        with urlopen(url+'/artifacts/evidence.json') as r:
            assert json.load(r)=={'state':{'frame':12}}
        for headers in ({},{'X-Inspector-Token':'secret','Origin':'http://evil.example'}):
            with pytest.raises(HTTPError) as e:urlopen(Request(url+'/api/stop',data=b'{}',headers=headers))
            assert e.value.code==403
        with urlopen(Request(url+'/api/stop',data=b'{}',headers={'X-Inspector-Token':'secret'})) as r:
            assert json.load(r)['stopping']
        with pytest.raises(HTTPError) as e:urlopen(url+'/artifacts/%2e%2e/secret')
        assert e.value.code==404
    finally:
        server.shutdown();thread.join();server.server_close()


def test_shared_session_release_cannot_mutate_a_replacement():
    class Bridge:
        def call(self,name,args):
            if name=='scrywrite_observe':return {'session':self.session,'focused':True,'mode':'control'}
            raise AssertionError('replacement must not receive mutations')
    bridge=Bridge();bridge.session='1-2';session=LiveSession(bridge)
    bridge.session='2-3'
    with pytest.raises(RuntimeError,match='original viewer'):session.release()
