"""Bounded binary display snapshots from the document's desktop view tools."""
import os
import struct
import time
import json
from pathlib import Path
import numpy as np
from fastapi import APIRouter, Request, HTTPException
from fastapi.concurrency import run_in_threadpool

router=APIRouter()
MAX_BYTES=256*1024*1024


def validate_and_rotate(data, rotation):
    if len(data)<48 or data[:8]!=b'NADOCVT1':
        raise HTTPException(422,detail='Invalid VR display header')
    schema,version,flags,triangles,lines,sprites,width,height,batches,ack=struct.unpack_from('<10I',data,8)
    if schema not in (4,5,6,7,8,9,10,11) or version<1 or (flags>=4096 or flags&(128|512|1024)) or triangles%3 or lines%2 or triangles+lines>4000000 or sprites>100000 or batches>10000 or width!=(768 if schema>=8 else 0 if schema>=6 else 2048) or height!=(768 if schema>=8 else 0 if schema>=6 else 2048) or len(data)>MAX_BYTES:
        raise HTTPException(422,detail='Invalid VR display dimensions')
    if schema in (9,11) and (triangles or lines or sprites or batches):raise HTTPException(422,detail='Panel-only update contains geometry')
    r=np.asarray(rotation,dtype=float)
    if r.shape!=(3,3) or not np.isfinite(r).all():raise HTTPException(422,detail='Invalid VR view rotation')
    result=bytearray(data);offset=48
    if schema>=7:
        if len(data)<52 or not 0<struct.unpack_from('<I',data,48)[0]<version:
            raise HTTPException(422,detail='Invalid VR transform base')
        offset=52
    def values(count, columns):
        nonlocal offset
        end=offset+count*columns*4
        if end>len(result):raise HTTPException(422,detail='Truncated VR display')
        a=np.frombuffer(result,dtype='<f4',count=count*columns,offset=offset).reshape((-1,columns))
        offset=end
        if not np.isfinite(a).all() or np.max(np.abs(a),initial=0)>1e9:raise HTTPException(422,detail='Invalid VR display values')
        return a
    stride=12 if schema>=5 else 9
    vertices=values(triangles+lines,stride);vertices[:,:3]=vertices[:,:3]@r.T
    if schema>=5:vertices[:,9:12]=vertices[:,9:12]@r.T
    labels=values(sprites,15);labels[:,:3]=labels[:,:3]@r.T
    total_vertices=triangles+lines;total_instances=0
    for _ in range(batches):
        if offset+8>len(result):raise HTTPException(422,detail='Truncated VR mesh')
        if schema==7:
            ni,columns=struct.unpack_from('<2I',result,offset);offset+=8
            total_instances+=ni
            if not ni or total_instances>1000000 or columns not in (3,12):
                raise HTTPException(422,detail='Invalid VR transform dimensions')
            transforms=values(ni,columns).reshape((-1,columns//3,3))
            transforms[:]=transforms@r.T
            continue
        nv,ni=struct.unpack_from('<2I',result,offset);offset+=8
        total_vertices+=nv;total_instances+=ni
        if nv%3 or not nv or not ni or total_vertices>4000000 or total_instances>1000000:
            raise HTTPException(422,detail='Invalid VR mesh dimensions')
        values(nv,stride)  # shared local geometry; rotate instance transforms instead
        instances=values(ni,20)
        matrix=instances[:,:16].reshape((-1,4,4))  # column-major columns
        matrix[:,:,:3]=matrix[:,:,:3]@r.T
    if schema>=10:
        expected=width*height*4
        if not 0<len(data)-offset<expected:raise HTTPException(422,detail='Invalid compressed VR panel size')
        if (len(data)-offset)%8:raise HTTPException(422,detail='Invalid compressed VR panel')
        counts=np.frombuffer(data,dtype='<u4',offset=offset)[::2]
        if not counts.size or not np.all(counts) or int(counts.sum(dtype=np.uint64))!=width*height:
            raise HTTPException(422,detail='Invalid compressed VR panel')
    elif len(data)!=offset+width*height*4:raise HTTPException(422,detail='Invalid VR display size')
    return result


@router.post('/vr/view-tools')
async def publish(request:Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    vr._require_local(request)
    tracing = os.environ.get('NADOC_VR_VIEW_PIPELINE') == '1'
    started = time.perf_counter()
    epoch_ms = time.time() * 1000
    marks = {}
    def mark(name):
        if tracing: marks[name] = (time.perf_counter() - started) * 1000
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_BYTES:raise HTTPException(413,detail='VR display snapshot too large')
    mark('body_end_ms')
    with vr._FEEDBACK_LOCK:
        state=vr._read_state()
        if not state or state.get('doc_id')!=get_current_doc():raise HTTPException(409,detail='VR belongs to another document or is unavailable')
    mark('state_end_ms')
    def validate():
        mark('validation_worker_start_ms')
        result = validate_and_rotate(data,state.get('view_rotation'))
        mark('validation_worker_end_ms')
        return result
    result=await run_in_threadpool(validate)
    mark('validation_end_ms')
    capabilities = {}
    def deliver():
        from backend.api.vr_view_transport import send_snapshot
        with vr._FEEDBACK_LOCK:
            current=vr._read_state()
            if not current or current.get('event_path')!=state.get('event_path') or current.get('doc_id')!=state.get('doc_id'):
                raise HTTPException(409,detail='VR session changed during upload')
        mark('write_start_ms')
        if send_snapshot(state['event_path'], result, capabilities=capabilities):
            mark('write_end_ms')
            return 'ipc'
        if struct.unpack_from('<I',result,8)[0]>=7:
            raise HTTPException(409,detail='VR transform stream unavailable; resend full snapshot')
        # Compatibility for already-running older viewers. Disk I/O runs in the
        # worker, never directly in the async request handler.
        with vr._FEEDBACK_LOCK:
            current=vr._read_state()
            if not current or current.get('event_path')!=state.get('event_path') or current.get('doc_id')!=state.get('doc_id'):
                raise HTTPException(409,detail='VR session changed during upload')
            path=Path(state['event_path']+'.viewtools');temp=Path(str(path)+'.next')
            temp.write_bytes(result)
            mark('file_end_ms')
            temp.chmod(0o600)
            mark('chmod_end_ms')
            os.replace(temp,path)
            mark('write_end_ms')
        return 'file'
    try:
        transport = await run_in_threadpool(deliver)
    except OSError as exc:
        raise HTTPException(503, detail='VR display transport unavailable') from exc
    if tracing:
        print('VR_VIEW_PIPELINE_BACKEND ' + json.dumps({'epoch_ms':epoch_ms,'version':struct.unpack_from('<I',result,12)[0],'bytes':len(result),'transport':transport,**marks}), flush=True)
    return {'published':True,'bytes':len(result),'compressed_panels':capabilities.get('compressed_panels',False),'atlas_patches':capabilities.get('atlas_patches',False),'transform_updates':capabilities.get('transform_updates',False) and os.environ.get('NADOC_VR_TRANSFORM_UPDATES')!='0'}


def parse_event(value):
    if not isinstance(value,dict) or type(value.get('sequence')) is not int or type(value.get('index')) is not int:return None
    if value['sequence']<1 or not 0<=value['index']<8:return None
    return {'sequence':value['sequence'],'index':value['index']}
