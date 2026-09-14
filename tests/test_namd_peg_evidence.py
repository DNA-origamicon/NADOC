import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from backend.core.namd_peg_evidence import read_energy_logs, pair_samples, continuation_epochs
from backend.core.namd_peg_health import polymer_plateau, assess_segment, validation_message

HEADER = 'ETITLE: TS POTENTIAL TOTAL TEMP BOUNDARY MISC\n'

def log(tmp, name, text):
    p = tmp/name; p.write_text(text); return p


def test_headerless_and_delayed_header_rows_are_retained(tmp_path):
    paths = [log(tmp_path, 'base', HEADER+'ENERGY: 0 -10 -8 294 0 0\n'),
             log(tmp_path, 'resume1', 'ENERGY: 10 -10 -8 294 0 0\n'),
             log(tmp_path, 'resume2', 'ENERGY: 20 -10 -8 294 0 0\n'+HEADER+'ENERGY: 30 -10 -8 294 0 0\n')]
    rows, _ = read_energy_logs(paths)
    assert [list(r) for r in rows] == [[0], [10], [20, 30]]
    assert rows[2][20]['POTENTIAL'] == -10


@pytest.mark.parametrize('bad', [
    'ENERGY: 0 -1 -2 294 nan 0\n',
    'ENERGY: 0 -1 -2 294 0\n',
    'ENERGY: 0 -1 -2 294 0 0\nENERGY: 0 -1 -2 294 0 0\n',
    'ENERGY: 1.5 -1 -2 294 0 0\n',
    'ETITLE: TS TOTAL POTENTIAL TEMP BOUNDARY MISC\n',
])
def test_incompatible_or_bad_evidence_is_not_silently_dropped(tmp_path, bad):
    with pytest.raises(ValueError, match='energy_'):
        read_energy_logs([log(tmp_path, 'base', HEADER), log(tmp_path, 'resume', bad)])


def test_no_schema_is_an_error(tmp_path):
    with pytest.raises(ValueError, match='energy_schema'):
        read_energy_logs([log(tmp_path, 'resume', 'ENERGY: 0 1 2 3\n')])


def test_restart_rolls_back_old_future_and_never_borrows_other_epoch_energy():
    samples = pair_samples([{10:'old10',20:'old20',30:'abandoned'}, {20:'new20'}],
                           [{10:{'TS':10},20:{'TS':20},30:{'TS':30}}, {}], [0,10])
    assert samples == {10:('old10',{'TS':10}),20:('new20',None)}


def test_continuations_use_numeric_order_not_mtime(tmp_path):
    for n in [10, 2, 1]:
        log(tmp_path, f'peg.resume{n}.log', '')
        log(tmp_path, f'peg.resume{n}.conf', f'firsttimestep {n*100}\n')
    assert [e[0] for e in continuation_epochs(tmp_path,'peg')] == [0,1,2,10]


@pytest.mark.parametrize('mutation', ['rg','height','energy','jump','sparse','nan','shape','volume'])
def test_skip_rejects_bad_or_unconverged_metrics(mutation):
    energy = [dict(POTENTIAL=-10000., VOLUME=1000.) for _ in range(30)]
    rg=np.full((30,4),8.); height=rg.copy()
    if mutation=='rg': rg[10:20,2] = np.linspace(8,12,10)
    if mutation=='height': height[-5:,0] = 14
    if mutation=='energy': energy[-1]['POTENTIAL'] = -5000
    if mutation=='jump': rg[-10:] = 12
    if mutation=='sparse': energy=energy[:19];rg=rg[:19];height=height[:19]
    if mutation=='nan': rg[-1,1]=np.nan
    if mutation=='shape': height=height[:,:3]
    if mutation=='volume': energy[-1].pop('VOLUME')
    assert not polymer_plateau(energy,rg,height)[0]


def test_skip_accepts_stationary_noisy_data_and_records_margins():
    energy=[dict(POTENTIAL=-10000.+(-1)**i) for i in range(30)]
    rg=np.array([[8.+.01*(-1)**i]*4 for i in range(30)])
    ok,d=polymer_plateau(energy,rg,rg*2)
    assert ok
    assert len(d['convergence']) == 9
    assert all(r['passed'] and len(r['windows'])==2 for r in d['convergence'].values())


def test_real_resumed_package_passes_without_rewriting_native_logs(tmp_path):
    source=Path('workspace/md_jobs/48c1995afbd5/package')
    if not (source/'peg_relax_p10.resume2.log').exists():
        pytest.skip('native continuation fixture unavailable')
    p=tmp_path/'package';shutil.copytree(source,p)
    # Deliberately reverse timestamps; semantics must remain resume1 then resume2.
    os.utime(p/'peg_relax_p10.resume1.log',(2e9,2e9))
    r=assess_segment(p,'peg_relax_p10')
    assert r['safe'] and not r['skip']
    assert r['energy_comparison_frames']==r['samples']==30
    assert not r['missing_energy_steps']
    assert r['max_force_energy_error_kcal_mol'] < .0001
    assert 'not a safety failure' in validation_message(r)
    # A real missing energy record must name the failed check and step.
    f=p/'peg_relax_p10.resume2.log'
    f.write_text('\n'.join(l for l in f.read_text().splitlines() if not (l.startswith('ENERGY:') and l.split()[1]=='120000'))+'\n')
    r=assess_segment(p,'peg_relax_p10')
    assert not r['safe'] and not r['skip']
    assert r['missing_energy_steps']==[120000]
    assert 'energy_frame_coverage' in validation_message(r) and '120000' in validation_message(r)


@pytest.mark.parametrize('values,limit', [
    ([9.75]*5+[10.25]*5, 'drift'),
    ([9.,11.]*5, 'fluctuation'),
])
def test_exact_threshold_does_not_count_as_converged(values, limit):
    from backend.core.namd_peg_health import series_report
    report=series_report(values*2,.05,.1)
    assert not report['passed']
    assert report['windows'][0][limit] == pytest.approx(report[f'{limit if limit == "drift" else "fluctuation"}_limit'])


def test_missing_checkpoint_blocks_skip_even_with_converged_metrics(tmp_path, monkeypatch):
    from backend.core import namd_peg_health as ph
    (tmp_path/'output').mkdir()
    monkeypatch.setattr(ph,'assess_segment',lambda *a: dict(safe=True,skip=True,
                                                         energy_plateaued=True,polymer_plateaued=True))
    r=ph.skip_decision(tmp_path,'p10',True,True)
    assert not r['skip'] and r['skip_blockers']==['missing_checkpoint:coor,vel,xsc']
    for ext in ('coor','vel','xsc'): (tmp_path/'output'/f'p10.{ext}').write_text('test checkpoint')
    assert ph.skip_decision(tmp_path,'p10',True,True)['skip']
    assert not ph.skip_decision(tmp_path,'p10',True,False)['skip']


@pytest.mark.parametrize('fault,expected', [
    ('wall','wall_penetration'), ('graft','graft_displacement'),
    ('force','force_energy_agreement'), ('gap','trajectory_coverage'),
    ('unfinished','native_completion'), ('offload','gpu_resident'),
    ('fatal','no_engine_errors'),
])
def test_individual_safety_checks_block_skip_and_name_failure(tmp_path,monkeypatch,fault,expected):
    import json
    from backend.core import namd_peg_health as ph
    (tmp_path/'output').mkdir()
    manifest=dict(n_atoms=2,slit=dict(box_nm=[4.8]*3,axis=2,inset_nm=.2,k_kcal_mol_A2=10.),
                  graft_k_kcal_mol_A2=5.,audit=dict(anchor_indices_0=[0],peg_indices_0=[0,1]),
                  segments=[dict(name='p10',steps=3000,dcd_freq=100)])
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    xyz=np.array([[10.,10.,4.],[10.,10.,6.]])
    monkeypatch.setattr(ph,'read_pair',lambda *a:dict(atoms=[['1','PEG'],['2','PEG']],xyz=xyz.copy()))
    samples={}
    for i in range(1,31):
        pos=xyz.copy();row=dict(TS=i*100,POTENTIAL=-10000.,TOTAL=-9000.,TEMP=294.,BOUNDARY=0.,MISC=0.)
        if fault=='wall': pos[1,2]=.9;row['MISC']=12.1
        if fault=='graft': pos[0,0]+=1.6;row['BOUNDARY']=12.8
        if fault=='force': row['MISC']=.101
        if fault=='gap' and i==1: continue
        samples[i*100]=(pos,row)
    native='Running with GPU-resident mode\nWRITING COORDINATES TO OUTPUT FILE AT STEP 3000\nEnd of program\n'
    if fault=='unfinished':native=native.replace('STEP 3000','STEP 2990')
    if fault=='offload':native=native.replace('Running with GPU-resident mode','')
    if fault=='fatal':native+='FATAL ERROR\n'
    monkeypatch.setattr(ph,'segment_evidence',lambda *a:(samples,native,['controlled-test-evidence']))
    result=ph.assess_segment(tmp_path,'p10')
    assert not result['safe'] and not result['skip']
    assert expected in result['failed_checks'] and expected in ph.validation_message(result)
