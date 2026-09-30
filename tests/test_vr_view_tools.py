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
