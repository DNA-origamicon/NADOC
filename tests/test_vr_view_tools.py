import struct
import numpy as np
import pytest
from fastapi import HTTPException
from backend.api.vr_view_tools import validate_and_rotate, parse_event


def packet():
    vertices=np.array([[1,2,3,1,0,0,1,-1,-1]]*3,dtype='<f4')
    return b'NADOCVT1'+struct.pack('<10I',4,2,3,3,0,0,2048,2048,0,7)+vertices.tobytes()+bytes(2048*2048*4)


def test_binary_display_rotates_geometry_and_preserves_colours_and_texture():
    data=packet();result=validate_and_rotate(data,[[0,0,1],[0,1,0],[-1,0,0]])
    assert list(np.frombuffer(result,dtype='<f4',offset=48,count=9))==[3,2,-1,1,0,0,1,-1,-1]
    assert result[-2048*2048*4:]==data[-2048*2048*4:]


def test_binary_limits_and_events():
    data=packet()
    with pytest.raises(HTTPException):validate_and_rotate(data[:-1],np.eye(3))
    invalid=bytearray(data);struct.pack_into('<f',invalid,48,float('nan'))
    with pytest.raises(HTTPException):validate_and_rotate(invalid,np.eye(3))
    for index in range(8):assert parse_event(dict(sequence=1,index=index))==dict(sequence=1,index=index)
    for value in [None,{},dict(sequence=True,index=0),dict(sequence=1,index=8),dict(sequence=1,index=9),dict(sequence=1,index=10)]:assert parse_event(value) is None


def test_instanced_mesh_rotates_pose_without_expanding_shared_geometry():
    vertices=np.array([[1,0,0,1,1,1,1,-1,-1]]*3,dtype='<f4')
    instance=np.r_[np.eye(4).T.reshape(-1),[.2,.4,.6,.8]].astype('<f4')
    instance[12:15]=[1,2,3]
    data=(b'NADOCVT1'+struct.pack('<10I',4,9,1,0,0,0,2048,2048,1,8)
          +struct.pack('<2I',3,1)+vertices.tobytes()+instance.tobytes()+bytes(2048*2048*4))
    result=validate_and_rotate(data,[[0,0,1],[0,1,0],[-1,0,0]])
    assert np.array_equal(np.frombuffer(result,dtype='<f4',offset=56,count=27),vertices.reshape(-1))
    posed=np.frombuffer(result,dtype='<f4',offset=56+108,count=20)
    assert list(posed[12:15])==[3,2,-1]
    assert np.allclose(posed[16:],[.2,.4,.6,.8])
    assert len(result)==len(data)

@pytest.mark.parametrize('flag',[128,512,1024])
def test_screen_layout_flags_are_rejected(flag):
    data=bytearray(packet());struct.pack_into('<I',data,16,flag)
    with pytest.raises(HTTPException):validate_and_rotate(data,np.eye(3))


def test_lit_display_rotates_normals_without_translation():
    vertices=np.array([[1,2,3,1,.5,.2,1,-1,-1,1,0,0]]*3,dtype='<f4')
    data=(b'NADOCVT1'+struct.pack('<10I',5,10,257,3,0,0,2048,2048,0,0)
          +vertices.tobytes()+bytes(2048*2048*4))
    result=validate_and_rotate(data,[[0,0,1],[0,1,0],[-1,0,0]])
    posed=np.frombuffer(result,dtype='<f4',offset=48,count=36).reshape(3,12)
    assert np.allclose(posed[:,:3],[[3,2,-1]]*3)
    assert np.allclose(posed[:,9:],[[0,0,-1]]*3)
    assert np.array_equal(posed[:,3:9],vertices[:,3:9])


def test_trajectory_update_reuses_atlas_and_still_rotates_normals():
    vertices = np.array([[1,2,3,1,.5,.2,1,-1,-1,1,0,0]]*3,dtype='<f4')
    data = b'NADOCVT1' + struct.pack('<10I',6,11,2048,3,0,0,0,0,0,0) + vertices.tobytes()
    result = validate_and_rotate(data, [[0,0,1],[0,1,0],[-1,0,0]])
    posed = np.frombuffer(result,dtype='<f4',offset=48).reshape(3,12)
    assert np.allclose(posed[:,:3], [[3,2,-1]]*3)
    assert np.allclose(posed[:,9:], [[0,0,-1]]*3)
    assert len(result) == 48 + 3*12*4
    with pytest.raises(HTTPException):
        validate_and_rotate(data[:-4], np.eye(3))
    invalid = bytearray(data)
    struct.pack_into('<I', invalid, 32, 2048)
    with pytest.raises(HTTPException):
        validate_and_rotate(invalid, np.eye(3))


@pytest.mark.parametrize("ipc", [False, True])
def test_opt_in_pipeline_trace_preserves_published_bytes(tmp_path, monkeypatch, capsys, ipc):
    import asyncio
    import json
    from types import SimpleNamespace
    from backend.api import routes_vr, doc_context, vr_view_transport
    from backend.api.vr_view_tools import publish
    data = b'NADOCVT1' + struct.pack('<10I',6,23,2048,0,0,0,0,0,0,0)
    state = {'doc_id':'trace-test', 'event_path':str(tmp_path/'event'), 'view_rotation':np.eye(3).tolist()}
    delivered = []
    def send(path, payload, **kwargs):
        delivered.append(bytes(payload))
        return ipc
    monkeypatch.setattr(vr_view_transport, 'send_snapshot', send)
    monkeypatch.setenv('NADOC_VR_VIEW_PIPELINE','1')
    monkeypatch.setattr(routes_vr,'_require_local',lambda _:None)
    monkeypatch.setattr(routes_vr,'_read_state',lambda:state)
    monkeypatch.setattr(doc_context,'get_current_doc',lambda:'trace-test')
    async def stream():
        yield data
    result = asyncio.run(publish(SimpleNamespace(stream=stream)))
    assert result == {'published':True,'bytes':len(data),'transform_updates':False}
    assert delivered == [data]
    if ipc:
        assert not (tmp_path/'event.viewtools').exists()
    else:
        assert (tmp_path/'event.viewtools').read_bytes() == data
    line = next(line for line in capsys.readouterr().out.splitlines() if line.startswith('VR_VIEW_PIPELINE_BACKEND '))
    trace = json.loads(line.split(' ',1)[1])
    assert trace['version'] == 23
    assert trace['transport'] == ('ipc' if ipc else 'file')
    assert 0 <= trace['body_end_ms'] <= trace['state_end_ms'] <= trace['validation_end_ms'] <= trace['write_start_ms'] <= trace['write_end_ms']


def test_transport_wait_does_not_block_async_handler(tmp_path, monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from backend.api import routes_vr, doc_context, vr_view_transport
    from backend.api.vr_view_tools import publish
    state = {'doc_id':'async-test','event_path':str(tmp_path/'event'),'view_rotation':np.eye(3).tolist()}
    monkeypatch.setattr(routes_vr,'_require_local',lambda _:None)
    monkeypatch.setattr(routes_vr,'_read_state',lambda:state)
    monkeypatch.setattr(doc_context,'get_current_doc',lambda:'async-test')
    started, release = threading.Event(), threading.Event()
    def send(*_, **kwargs):
        started.set()
        assert release.wait(1), 'Transport blocked the async event loop'
        return True
    monkeypatch.setattr(vr_view_transport,'send_snapshot',send)
    async def stream():
        yield b'NADOCVT1'+struct.pack('<10I',6,1,2048,0,0,0,0,0,0,0)
    async def scenario():
        task=asyncio.create_task(publish(SimpleNamespace(stream=stream)))
        while not started.is_set():
            await asyncio.sleep(.001)
        release.set()
        assert (await task)['published']
    asyncio.run(scenario())
