"""Destructive thinning is exercised exclusively on synthetic temporary files."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from backend.core import trajectory_thinning as thin
from backend.core.dcd_fast import read_frame, read_layout


def dcd(path, n=11, endian='<', cell=True, start=10):
    controls = [0]*20
    controls[0:4] = [n, start, 10, start+(n-1)*10]
    controls[9] = struct.unpack(endian+'i', struct.pack(endian+'f', .002/.04888821))[0]
    controls[10] = int(cell); controls[19] = 24
    def record(f, data):
        f.write(struct.pack(endian+'i',len(data))); f.write(data); f.write(struct.pack(endian+'i',len(data)))
    with path.open('wb') as f:
        record(f,b'CORD'+struct.pack(endian+'20i',*controls))
        record(f,struct.pack(endian+'i',1)+b'test'.ljust(80))
        record(f,struct.pack(endian+'i',4))
        for i in range(n):
            if cell: record(f,struct.pack(endian+'6d',30+i,0,31+i,0,0,32+i))
            xyz=np.array([[0,0,0],[1+i*.01,0,0],[0,1,0],[0,0,1]],dtype=float)+i
            for axis in range(3):record(f,np.asarray(xyz[:,axis],dtype=endian+'f4').tobytes())
    return path


def source(tmp_path, name='a.dcd', **kwargs):
    p=dcd(tmp_path/name,**kwargs)
    psf=tmp_path/'test.psf'
    psf.write_text('PSF\n\n       1 !NTITLE\n REMARKS test\n\n       4 !NATOM\n'+''.join(f'{i+1:8d} D000 1 DA C{i+1} C 0.000000 12.0110 0\n' for i in range(4))+'\n       3 !NBOND: bonds\n       1       2       1       3       1       4\n\n       0 !NTHETA: angles\n\n       0 !NPHI: dihedrals\n\n       0 !NIMPHI: impropers\n\n       0 !NDON: donors\n\n       0 !NACC: acceptors\n')
    return {'path':p,'topology':psf,'wrapped':False}


@pytest.mark.parametrize('endian',['<','>'])
@pytest.mark.parametrize('cell',[False,True])
def test_kept_records_exact_and_timing_readable(tmp_path,endian,cell):
    s=source(tmp_path,endian=endian,cell=cell,start=100)
    old=s['path'].read_bytes();d=thin.layout(s['path'])
    result=thin.apply([s],4,thin.fingerprint([s]),tmp_path)
    new=thin.layout(s['path']);raw=s['path'].read_bytes()
    assert new.n_frames==3 and new.istart==100 and new.nsavc==40
    assert new.first_ps==d.first_ps and new.delta_ps==pytest.approx(d.delta_ps*4)
    for j,i in enumerate([0,4,8]):
        assert raw[new.header_bytes+j*new.frame_bytes:new.header_bytes+(j+1)*new.frame_bytes]==old[d.header_bytes+i*d.frame_bytes:d.header_bytes+(i+1)*d.frame_bytes]
    from MDAnalysis.coordinates.DCD import DCDReader
    with DCDReader(str(s['path'])) as reader:
        assert len(reader)==3
        # MDAnalysis 2.10's big-endian DELTA decoder is faulty even on the
        # original fixture; timing for that case is checked via read_layout above.
        if endian == '<':
            assert reader[1].time-reader[0].time==pytest.approx(d.delta_ps*4)
        assert np.allclose(reader[2].positions,read_frame(s['path'],new,2)[0])
    assert result['saved_bytes']==len(old)-len(raw)
    assert not list(tmp_path.glob('.*original*'))
    assert not (tmp_path/'.trajectory-thinning.json').exists()


def test_preview_actual_rmsd_and_repeat_thinning(tmp_path):
    s=source(tmp_path,n=101)
    p=thin.preview([s]);assert p['options'][1]['sample_pairs']>0
    assert p['options'][1]['median_rmsd_A']>0
    assert p['options'][1]['spacing_ps']==pytest.approx([.04])
    thin.apply([s],2,p['fingerprint'],tmp_path)
    p2=thin.preview([s]);assert p2['source_frames']==51
    assert p2['options'][1]['spacing_ps']==pytest.approx([.08])
    thin.apply([s],2,p2['fingerprint'],tmp_path)
    assert thin.layout(s['path']).n_frames==26


def test_changed_source_rejects_without_writes(tmp_path):
    s=source(tmp_path);fp=thin.fingerprint([s]);os.utime(s['path'],ns=(1,1));original=s['path'].read_bytes()
    with pytest.raises(ValueError,match='changed since'):
        thin.apply([s],2,fp,tmp_path)
    assert s['path'].read_bytes()==original


def test_multi_file_replace_failure_rolls_back(tmp_path,monkeypatch):
    sources=[source(tmp_path,'a.dcd'),source(tmp_path,'b.dcd')]
    original=[s['path'].read_bytes() for s in sources];replace=os.replace
    def fail(src,dst):
        if '.thin-' in str(src) and Path(dst).name=='b.dcd':raise OSError('injected failure')
        return replace(src,dst)
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError,match='injected'):
        thin.apply(sources,2,thin.fingerprint(sources),tmp_path)
    assert [s['path'].read_bytes() for s in sources]==original
    assert not list(tmp_path.glob('.*original*'))


def test_corrupt_or_torn_records_preserve_original(tmp_path):
    s=source(tmp_path);p=s['path'];d=read_layout(p)
    with p.open('r+b') as f:f.seek(d.header_bytes+52);f.write(b'bad!')
    original=p.read_bytes()
    with pytest.raises(ValueError,match='record'):
        thin.apply([s],2,thin.fingerprint([s]),tmp_path)
    assert p.read_bytes()==original
    with p.open('ab') as f:f.write(b'torn')
    with pytest.raises(ValueError,match='incomplete'):thin.preview([s])


def test_ready_recheck_failure_preserves_original(tmp_path):
    s=source(tmp_path);original=s['path'].read_bytes()
    def reject():raise ValueError('Job is active')
    with pytest.raises(ValueError,match='active'):
        thin.apply([s],2,thin.fingerprint([s]),tmp_path,check_ready=reject)
    assert s['path'].read_bytes()==original


def test_recover_interrupted_transaction(tmp_path):
    s=source(tmp_path);p=s['path'];old=p.read_bytes();backup=tmp_path/'.backup';temp=tmp_path/'.temp'
    os.link(p,backup);temp.write_bytes(b'new');os.replace(temp,p)
    (tmp_path/'.trajectory-thinning.json').write_text(json.dumps({'state':'prepared','files':[{'source':str(p),'backup':str(backup),'temp':str(temp)}]}))
    thin.recover(tmp_path)
    assert p.read_bytes()==old


def test_explicit_confirmation_required_and_active_job_rejected(monkeypatch):
    from contextlib import contextmanager
    from fastapi import HTTPException
    from backend.api import routes_md_thinning as route, routes_md
    from types import SimpleNamespace
    @contextmanager
    def fake_files(_):yield Path('/tmp'),[]
    monkeypatch.setattr(route,'_job_files',fake_files)
    with pytest.raises(HTTPException) as exc:
        route._run('test',route.ThinJobRequest(stride=2,fingerprint='x'))
    assert exc.value.status_code==400
    monkeypatch.setattr(routes_md,'_load_job',lambda _:SimpleNamespace(status=SimpleNamespace(value='running')))
    with pytest.raises(HTTPException) as exc:route._ready('test')
    assert exc.value.status_code==409


def test_http_preview_and_apply_roundtrip(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_md_thinning as route
    s=source(tmp_path,n=101)
    @contextmanager
    def files(_):yield tmp_path,[s]
    monkeypatch.setattr(route,'_job_files',files)
    monkeypatch.setattr(route,'_ready',lambda _:None)
    app=FastAPI();app.include_router(route.router);client=TestClient(app)
    preview=client.post('/md/jobs/example/thin/preview');assert preview.status_code==200
    fp=preview.json()['fingerprint']
    assert client.post('/md/jobs/example/thin',json={'stride':2,'fingerprint':fp}).status_code==400
    assert client.post('/md/jobs/example/thin',json={'stride':2.5,'fingerprint':fp,'confirmed':True}).status_code==422
    result=client.post('/md/jobs/example/thin',json={'stride':2,'fingerprint':fp,'confirmed':True})
    assert result.status_code==200 and result.json()['frames_kept']==51
    assert client.post('/md/jobs/example/thin',json={'stride':2,'fingerprint':fp,'confirmed':True}).status_code==409


def test_insufficient_space_preserves_original(tmp_path,monkeypatch):
    from types import SimpleNamespace
    s=source(tmp_path);old=s['path'].read_bytes()
    monkeypatch.setattr(thin.shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match='free space'):
        thin.apply([s],2,thin.fingerprint([s]),tmp_path)
    assert s['path'].read_bytes()==old


def test_wrapped_preview_has_coordinates_and_no_writes(tmp_path):
    s=source(tmp_path,n=21);s['wrapped']=True;old=s['path'].read_bytes()
    result=thin.preview([s])
    assert result['options'][1]['sample_pairs']>0
    assert s['path'].read_bytes()==old
