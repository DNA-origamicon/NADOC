"""Software-only UV cache/geometry checks; no native simulations or authored designs."""
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core import uv_crosslinking as uv


def sites():
    return [dict(id=f'D{i}:1',segid=f'D{i}',resid=1,base=b,label=b,
                 display_key=f'h:{i}:FORWARD',c5_serial=2*i,c6_serial=2*i+1)
            for i,b in enumerate('TCT')]


def coordinates():
    return np.array([[5,5,5],[6.4,5,5],[5,8.4,5],[6.4,8.4,5],
                     [5,11.8,5],[6.4,11.8,5]],dtype=np.float32)


def test_checkpoint_counts_all_chemistries_and_uses_all_frames(tmp_path):
    db=uv._connect(tmp_path)
    with db:
        uv._put(db,'sites',sites());uv._put(db,'total',2)
    uv.accumulate_frame(db,coordinates(),[40,40,40,90,90,90],sites(),0)
    partial=uv.read_result(tmp_path)
    assert partial['ready'] and not partial['complete']
    assert uv.progress(tmp_path)['fraction']==.5
    assert {p['chemistry'] for p in partial['pairs']}=={'TC','CT'}
    assert all(p['opportunity']==1 for p in partial['pairs'])
    far=coordinates();far[2:4,1]+=10
    uv.accumulate_frame(db,far,[40,40,40,90,90,90],sites(),1)
    db.close()
    result=uv.read_result(tmp_path)
    assert result['complete'] and result['n_sampled_frames']==2
    assert uv.progress(tmp_path)['phase']=='complete'
    assert all(p['opportunity']==.5 for p in result['pairs'])
    assert all(p['tt_contact_mean'] is None for p in result['pairs'])


def test_resume_seeks_first_uncommitted_frame_and_complete_load_needs_no_universe(tmp_path,monkeypatch):
    import MDAnalysis as mda
    visits=[]
    class Trajectory:
        def __len__(self):return 3
        def __getitem__(self,i):
            visits.append(i)
            return SimpleNamespace(positions=coordinates(),dimensions=[40,40,40,90,90,90])
        def close(self):pass
    monkeypatch.setattr(mda,'Universe',lambda *a:SimpleNamespace(trajectory=Trajectory()))
    monkeypatch.setattr(uv,'pyrimidine_sites',lambda *a:sites())
    first=uv.analyze('fake.psf',['fake.dcd'],None,tmp_path,{},frame_limit=1)
    assert first['n_sampled_frames']==1 and visits==[0]
    second=uv.analyze('fake.psf',['fake.dcd'],None,tmp_path,{})
    assert visits==[0,1,2] and second['complete']
    monkeypatch.setattr(mda,'Universe',lambda *a:pytest.fail('cache reopened trajectory'))
    assert uv.analyze('fake.psf',['fake.dcd'],None,tmp_path,{})==second


def test_failed_frame_does_not_advance_checkpoint(tmp_path):
    db=uv._connect(tmp_path)
    with db:
        uv._put(db,'sites',sites());uv._put(db,'total',2)
    uv.accumulate_frame(db,coordinates(),None,sites(),0)
    bad=coordinates();bad[0,0]=np.nan
    with pytest.raises(ValueError,match='Nonfinite'):
        uv.accumulate_frame(db,bad,None,sites(),1)
    assert uv.read_result(tmp_path)['n_sampled_frames']==1
    db.close()


def test_periodic_screen_and_tt_contact_score(tmp_path):
    ss=sites()[:2];ss[1]['base']='T'
    xyz=coordinates()[:4];xyz[2:,1]-=40
    db=uv._connect(tmp_path)
    with db:
        uv._put(db,'sites',ss);uv._put(db,'total',1)
    uv.accumulate_frame(db,xyz,[40,40,40,90,90,90],ss,0)
    pair=uv.read_result(tmp_path)['pairs'][0]
    assert pair['opportunity']==1
    assert pair['min_distance_ang']==pytest.approx(3.4,abs=1e-5)
    assert 0<pair['tt_contact_mean']<1
    db.close()


def test_cache_changes_with_inputs_but_not_location(tmp_path):
    p=tmp_path/'a.psf';p.write_text('psf')
    t=tmp_path/'a.dcd';t.write_text('frames')
    design=SimpleNamespace(model_dump_json=lambda:'{"id":"x"}')
    old,_=uv.cache_spec(tmp_path,p,[t],design)
    same,_=uv.cache_spec(tmp_path,p,[t],design)
    assert same==old
    t.write_text('more frames')
    new,_=uv.cache_spec(tmp_path,p,[t],design)
    assert new!=old


def test_empty_pyrimidine_set_finishes_with_zero_candidates(tmp_path):
    db=uv._connect(tmp_path)
    with db:
        uv._put(db,'sites',[]);uv._put(db,'total',1)
    uv.accumulate_frame(db,np.zeros((0,3)),None,[],0)
    assert uv.read_result(tmp_path)['complete']
    assert uv.read_result(tmp_path)['pairs']==[]
    db.close()


def test_export_mapping_not_naive_residue_numbering_and_formed_sites_excluded(monkeypatch):
    from backend.core import atomistic_to_nadoc as mapping
    domain=SimpleNamespace(helix_id='h',start_bp=0,end_bp=10,
                           direction=SimpleNamespace(value='FORWARD'),overhang_id=None)
    strand=SimpleNamespace(domains=[domain],strand_type=SimpleNamespace(value='scaffold'))
    design=SimpleNamespace(helices=[SimpleNamespace(id='h',label='H')],strands=[strand,strand])
    monkeypatch.setattr(mapping,'load_segid_chain_map',lambda p:{'D001':'B'})
    monkeypatch.setattr(mapping,'build_namd_coarse_reference',lambda *a,**kw:({('B',3):('h',0,'FORWARD')},{}))
    carbon=SimpleNamespace(index=4,resindex=0,bonded_atoms=[])
    atoms=SimpleNamespace(select_atoms=lambda selection:[carbon])
    residue=SimpleNamespace(resname='THY',segid='D001',resid=3,atoms=atoms)
    universe=SimpleNamespace(residues=[residue],bonds=[])
    site=uv.pyrimidine_sites(universe,design,'.')[0]
    assert site['display_key']=='h:0:FORWARD'
    assert site['label']=='Scaffold - H[0]'
    carbon.bonded_atoms=[SimpleNamespace(resindex=1,name='C5')]
    assert uv.pyrimidine_sites(universe,design,'.')==[]


def test_worker_kill_preserves_committed_frame_with_normal_wal(tmp_path):
    import select
    import subprocess
    import sys
    db=uv._connect(tmp_path)
    with db:
        uv._put(db,'sites',sites());uv._put(db,'total',2)
    db.close()
    code='''
import json,sys,time,numpy as np
from backend.core import uv_crosslinking as uv
db=uv._connect(sys.argv[1])
sites=json.loads(db.execute("SELECT value FROM state WHERE key='sites'").fetchone()[0])
xyz=np.array([[5,5,5],[6.4,5,5],[5,8.4,5],[6.4,8.4,5],[5,11.8,5],[6.4,11.8,5]],dtype=np.float32)
uv.accumulate_frame(db,xyz,None,sites,0)
print('committed',flush=True)
time.sleep(60)
'''
    proc=subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],stdout=subprocess.PIPE,text=True)
    try:
        assert select.select([proc.stdout],[],[],5)[0], 'worker did not checkpoint'
        assert proc.stdout.readline().strip()=='committed'
    finally:
        proc.kill();proc.wait(timeout=5)
        proc.stdout.close()
    result=uv.read_result(tmp_path)
    assert result['n_sampled_frames']==1
    assert all(p['reactive_frames']==1 for p in result['pairs'])
