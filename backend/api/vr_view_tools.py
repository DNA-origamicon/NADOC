"""Bounded binary display snapshots from the document's desktop view tools."""
import os
import struct
from pathlib import Path
import numpy as np
from fastapi import APIRouter, Request, HTTPException

router=APIRouter()
MAX_BYTES=256*1024*1024


def validate_and_rotate(data, rotation):
    if len(data)<48 or data[:8]!=b'NADOCVT1':
        raise HTTPException(422,detail='Invalid VR display header')
    schema,version,flags,triangles,lines,sprites,width,height,batches,ack=struct.unpack_from('<10I',data,8)
    if schema!=4 or version<1 or (flags>=4096 or flags&(128|512|1024)) or triangles%3 or lines%2 or triangles+lines>4000000 or sprites>100000 or batches>10000 or width!=2048 or height!=2048 or len(data)>MAX_BYTES:
        raise HTTPException(422,detail='Invalid VR display dimensions')
    r=np.asarray(rotation,dtype=float)
    if r.shape!=(3,3) or not np.isfinite(r).all():raise HTTPException(422,detail='Invalid VR view rotation')
    result=bytearray(data);offset=48
    def values(count, columns):
        nonlocal offset
        end=offset+count*columns*4
        if end>len(result):raise HTTPException(422,detail='Truncated VR display')
        a=np.frombuffer(result,dtype='<f4',count=count*columns,offset=offset).reshape((-1,columns))
        offset=end
        if not np.isfinite(a).all() or np.max(np.abs(a),initial=0)>1e9:raise HTTPException(422,detail='Invalid VR display values')
        return a
    vertices=values(triangles+lines,9);vertices[:,:3]=vertices[:,:3]@r.T
    labels=values(sprites,15);labels[:,:3]=labels[:,:3]@r.T
    total_vertices=triangles+lines;total_instances=0
    for _ in range(batches):
        if offset+8>len(result):raise HTTPException(422,detail='Truncated VR mesh')
        nv,ni=struct.unpack_from('<2I',result,offset);offset+=8
        total_vertices+=nv;total_instances+=ni
        if nv%3 or not nv or not ni or total_vertices>4000000 or total_instances>1000000:
            raise HTTPException(422,detail='Invalid VR mesh dimensions')
        values(nv,9)  # shared local geometry; rotate instance transforms instead
        instances=values(ni,20)
        matrix=instances[:,:16].reshape((-1,4,4))  # column-major columns
        matrix[:,:,:3]=matrix[:,:,:3]@r.T
    if len(data)!=offset+width*height*4:raise HTTPException(422,detail='Invalid VR display size')
    return result


@router.post('/vr/view-tools')
async def publish(request:Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_BYTES:raise HTTPException(413,detail='VR display snapshot too large')
    with vr._FEEDBACK_LOCK:
        state=vr._read_state()
        if not state or state.get('doc_id')!=get_current_doc():raise HTTPException(409,detail='VR belongs to another document or is unavailable')
        result=validate_and_rotate(data,state.get('view_rotation'))
        path=Path(state['event_path']+'.viewtools');temp=Path(str(path)+'.next')
        temp.write_bytes(result);temp.chmod(0o600);os.replace(temp,path)
    return {'published':True,'bytes':len(result)}


def parse_event(value):
    if not isinstance(value,dict) or type(value.get('sequence')) is not int or type(value.get('index')) is not int:return None
    if value['sequence']<1 or not 0<=value['index']<8:return None
    return {'sequence':value['sequence'],'index':value['index']}
