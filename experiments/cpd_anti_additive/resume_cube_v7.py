"""Audit paused native data and resume only the remaining 0.46 ns of segment02."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import load_engine,admission
ROOT=REPO/'.development-artifacts/cpd-anti-gpu-cube-context-v5'


def partial_rows(path,first,last):
    lines=path.read_text().splitlines();assert not any('FATAL ERROR' in l for l in lines)
    headers=[l.split()[1:] for l in lines if l.startswith('ETITLE:')];assert headers and all(h==headers[0] for h in headers)
    records={}
    for line in lines:
        if not line.startswith('ENERGY:'):continue
        values=list(map(float,line.split()[1:]));assert len(values)==len(headers[0]) and np.isfinite(values).all()
        row=dict(zip(headers[0],values));step=int(row['TS'])
        if first<=step<=last:records[step]=row
    assert sorted(records)==list(range(first,last+1,1000))
    return records


def audit(output):
    old=read(ROOT/'validation_anti_1_v6.json');m=load_engine(old)
    pins=read(ROOT/'preparation_anti_1_v6.json')['inputs'][:]
    for pin in pins:checked(pin)
    pause=read(ROOT/'campaign_pause_v6.json');cp=pause['latest_complete_checkpoint'];assert cp['step']==1300000
    for p in cp['files']:checked(p);pins.append(p)
    base=ROOT/'anti/replica-1/validation';summaries=[]
    for name,first,last in [('segment-01',530000,1030000),('segment-02',1030000,1300000)]:
        f=base/name;rows=partial_rows(f/'run.log',first,last)
        cfg=(f/'run.conf').read_text();log=(f/'run.log').read_text()
        for text in ['GPUresident on','vdwForceSwitching on','LangevinPiston on','timestep 2','PMEGridSizeX 144','restartfreq 50000']:assert text+'\n' in cfg
        for text in ['Running with GPU-resident mode','VDW FORCE SWITCHING ACTIVE','LANGEVIN PISTON PRESSURE CONTROL ACTIVE']:assert text in log
        if name=='segment-01':
            assert read(f/'native_exit.json')['returncode']==0;m.parse_log(f/'run.log')
            a=read(f/'assessment.json');assert a['native_and_registered_geometry_passed']
            for p in a['checkpoints']:checked(p);pins.append(p)
            ref=m.parse_log(f/'endpoint-reference/run.log')[-1]
            assert abs(ref['POTENTIAL']-rows[last]['POTENTIAL'])<=max(.01,1e-6*abs(rows[last]['POTENTIAL']))
        prior=m.parse_log((ROOT/'anti/replica-1/restart/run.log') if name=='segment-01' else base/'segment-01/run.log')[-1]
        assert abs(rows[first]['POTENTIAL']-prior['POTENTIAL'])<=max(.01,1e-6*abs(prior['POTENTIAL']))
        layout=m.read_layout(f/'result.dcd');count=(last-first)//5000
        assert layout.n_atoms==m.N and layout.nsavc==5000 and layout.istart==first+5000 and layout.n_frames>=count
        xst=np.atleast_2d(np.loadtxt(f/'result.xst'));cells={int(r[0]):r[1:10].reshape(3,3) for r in xst}
        records=[];checkpoints=[]
        for i in range(count):
            x,cell=m.read_frame(f/'result.dcd',layout,i);dims=m.cell_to_dimensions(cell);step=first+(i+1)*5000;box=np.array(dims[:3])
            assert np.allclose(dims[3:],90) and np.allclose(cells[step],np.diag(box),rtol=0,atol=1e-3)
            assert abs(np.prod(box)-rows[step]['VOLUME'])<1
            g=m.physical('anti',x,box,True);assert g['passed']
            obs=m.observables(x.astype(float),read(ROOT/'observables_registration.json'),'anti');json.dumps(obs,allow_nan=False)
            records.append(dict(step=step,image_A=g['image_clearance_A'],observables=obs))
            if step%50000==0:
                prefix=f/f'checkpoint.{step}';b,r=m.box_from_xsc(Path(str(prefix)+'.xsc'));assert r[0]==step and np.allclose(b,box,atol=1e-3)
                coor=m.read_binary(Path(str(prefix)+'.coor'),m.N);vel=m.read_binary(Path(str(prefix)+'.vel'),m.N);assert np.isfinite(vel).all()
                assert np.all(abs(coor-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
                checkpoints.append(step)
                pins += [source(Path(str(prefix)+'.'+e)) for e in ['coor','vel','xsc']]
        summaries.append(dict(segment=name,through_step=last,frames=count,minimum_image_A=min(v['image_A'] for v in records),checkpoints=checkpoints,records=records,statistics=m.statistics(list(rows.values()),1000)))
        pins += [source(f/n) for n in ['run.conf','run.log','result.dcd','result.xst']]
    prefix=Path(cp['prefix']);box,row=m.box_from_xsc(Path(str(prefix)+'.xsc'));x=m.read_binary(Path(str(prefix)+'.coor'),m.N)
    g=m.physical('anti',x,box);assert g['passed']
    result=dict(at=now(),passed=True,checkpoint=cp,checkpoint_geometry=g,checkpoint_potential=rows[1300000]['POTENTIAL'],segments=summaries,inputs=pins+[source(ROOT/'campaign_pause_v6.json'),source(Path(__file__))],scope='154 saved frames replayed through checkpoint,16 complete periodic restart sets,full cell/chemistry and registered observables; no acceptance of discarded tail or minimum certification.',simulation_ready=False)
    save(output,result);print(json.dumps(dict(passed=True,frames=sum(s['frames'] for s in summaries),checkpoint=cp['step'],minimum_image_A=min(s['minimum_image_A'] for s in summaries))))


def run(plan_path):
    p=admission(read(plan_path));m=load_engine(p);audit=read(checked(p['audit']));assert audit['passed']
    cp=Path(audit['checkpoint']['prefix']);first=1300000;steps=230000
    out=Path(p['output']);out.mkdir(exist_ok=False)
    # Static CPU check at exact saved checkpoint; do not use interrupted log's last energy.
    ref=m.native(out/'checkpoint-reference',m.config('anti',Path(str(cp)+'.coor'),first,p['seed'],cp,False,False)+'run 0\n',p['deadline_epoch'],4,False)
    prior=audit['checkpoint_potential'];limit=max(.01,1e-6*abs(prior));assert abs(ref[-1]['POTENTIAL']-prior)<=limit
    stage=out/'segment-02-remainder'
    rows=m.native(stage,m.config('anti',Path(str(cp)+'.coor'),first,p['seed'],cp,True,True,5000)+f'run {steps}\noutput result.restart\noutput result\n',p['deadline_epoch'])
    error=abs(rows[0]['POTENTIAL']-prior);assert error<=limit
    result=m.review('anti',stage,first,steps,5000,rows,p['deadline_epoch'],True)
    result.update(restart_error_kcal=error,restart_limit_kcal=limit,endpoint_reference=m.endpoint_reference('anti',stage,first+steps,p['seed'],rows,p['deadline_epoch'],4))
    save(stage/'assessment.json',result)
    save(out/'assessment.json',dict(at=now(),passed=True,continued_ns=.46,validation_endpoint_ns=2,remaining_validation_ns=8,assessment=source(stage/'assessment.json'),model_review_required=True,simulation_ready=False,minimum_certified=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['audit','run']);p.add_argument('path',type=Path);a=p.parse_args()
    if a.mode=='audit':audit(a.path)
    else:run(a.path)
