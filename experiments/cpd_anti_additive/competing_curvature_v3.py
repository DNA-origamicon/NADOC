"""Two-step constrained directional curvature at the two exposed +30 QM basins.

Checks only the direction connecting the conformations, not a full Hessian or
minimum certificate. Native electronic settings and existing stereo are fixed.
"""
import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import BOHR,save,now,geometry_audit
from backend.parameterization.photoproduct_qm import _dihedral_degrees
ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-competing-curvature-v3-20261003'


def normal(x,ids):
    n=np.zeros_like(x);step=1e-5
    for i in ids:
        for a in range(3):
            p=x.copy();m=x.copy();p[i,a]+=step;m[i,a]-=step
            n[i,a]=((_dihedral_degrees(*p[ids])-_dihedral_degrees(*m[ids])+180)%360-180)/(2*step)
    return n


def retract(x,ids,target):
    x=x.copy()
    for _ in range(12):
        error=(_dihedral_degrees(*x[ids])-target+180)%360-180
        if abs(error)<1e-9:return x
        n=normal(x,ids);x-=n*error/np.sum(n*n)
    raise RuntimeError('Constraint retraction failed')


def prepare():
    from ase import Atoms
    from ase.build import minimize_rotation_and_translation
    review=ART/'cpd-anti-competing-basin-review-v3-20261003/native_audit.json'
    audited=read(review)['records'];old=ART/'cpd-anti-competing-qm-v3-20261003'
    pilot=read(ART/'cpd-anti-sella-fresh-v1/plan.json')
    ROOT.mkdir(exist_ok=False);shutil.copyfile(__file__,ROOT/'worker.py')
    names=['plus30-qm-reference','plus30-mm-trial1'];basins=[];cases=[];sources=[source(review)]
    for name in names:
        record=next(r for r in audited if r['case']==name);assert record['native_stationarity_verified']
        result=read(checked(record['last_result']));plan=read(old/name/'plan.json')
        basins.append(dict(label=name,x=np.load(checked(result['geometry'])),plan=plan,
            energy=result['energy'],result=record['last_result']))
        sources += [record['last_result'],result['geometry'],result['native'],source(old/name/'plan.json'),plan['record']['model_graph']]
    for a,b in [(basins[0],basins[1]),(basins[1],basins[0])]:
        plan=a['plan'];x=np.asarray(a['x']);ids=plan['record']['torsion_indices'];target=plan['record']['target_degrees']
        ref=Atoms(plan['elements'],positions=x*BOHR);other=Atoms(plan['elements'],positions=np.asarray(b['x'])*BOHR)
        minimize_rotation_and_translation(ref,other)
        q=other.positions/BOHR-x;n=normal(x,ids);q-=n*np.sum(n*q)/np.sum(n*n);q/=np.linalg.norm(q)
        assert abs(np.sum(n*q))<1e-8
        basin_dir=ROOT/a['label'];basin_dir.mkdir()
        np.save(basin_dir/'direction.npy',q)
        for h in [.02,.04]:
            for sign in [-1,1]:
                label=f"{a['label']}-{sign*h:+.2f}"
                folder=ROOT/label;folder.mkdir();y=retract(x+sign*h*q,ids,target)
                graph=read(checked(plan['record']['model_graph']));audit=geometry_audit(y,dict(plan,geometry_bohr=x.tolist()),graph)
                assert audit['chemistry_passed'] and audit['constraint_passed']
                data=dict(label=label,basin=a['label'],step_bohr=sign*h,elements=plan['elements'],geometry_bohr=y.tolist(),seed_audit=audit)
                save(folder/'input.json',data);cases.append(dict(label=label,input=source(folder/'input.json')))
        a['x']=x.tolist();a['direction']=source(basin_dir/'direction.npy')
    master=dict(at=now(),cases=cases,basins=basins,sources=sources,
        runtime_sources=pilot['runtime_sources'],versions=pilot['versions'],runtime_python=pilot['runtime_python'],psi4_version=pilot['psi4_version'],
        method=pilot['method'],options=pilot['options'],threads=4,memory_gib=6,service_memory_gib=12,
        max_gradients=8,wall_seconds=3600,expected_seconds=1800,
        campaign=source(ART/'cpd-anti-readiness-v3-20261003/contract.json'),
        claim='Constrained directional curvature along aligned basin separation at0.02/0.04bohr. Not all-mode local stability or a global minimum.',
        acceptance=dict(positive_energy_curvature=True,step_halving_relative_difference=.1),
        minimum_certified=False,simulation_ready=False)
    save(ROOT/'plan.json',master);save(ROOT/'inputs_lock.json',dict(files=[source(p) for p in ROOT.rglob('*') if p.is_file()]))
    save(ROOT/'registration.json',dict(plan=source(ROOT/'plan.json'),inputs=source(ROOT/'inputs_lock.json')))
    print('Prepared eight constrained displacements; no new QM.')


def validate():
    reg=read(ROOT/'registration.json');p=read(checked(reg['plan']))
    for pin in read(checked(reg['inputs']))['files']+p['sources']+p['runtime_sources']:checked(pin)
    for name,version in p['versions'].items():assert metadata.version(name)==version
    assert len(p['cases'])==p['max_gradients']==8
    assert time.time()<read(checked(p['campaign']))['deadline_epoch']
    return p


def case(label):
    import psi4
    p=validate();assert psi4.__version__==p['psi4_version']
    c=next(c for c in p['cases'] if c['label']==label);data=read(checked(c['input']));folder=ROOT/label
    with (folder/'started.json').open('x') as f:f.write('{}\n')
    os.chdir(folder);scratch=folder/'scratch';scratch.mkdir()
    psi4.set_num_threads(4);psi4.set_memory('6 GiB');psi4.set_options(p['options'])
    psi4.core.IOManager.shared_object().set_default_path(str(scratch));psi4.set_output_file(str(folder/'output.dat'),False)
    x=np.array(data['geometry_bohr']);text='\n'.join(e+' '+' '.join(f'{v:.15f}' for v in xyz) for e,xyz in zip(data['elements'],x))
    mol=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    gradient,wfn=psi4.gradient(p['method'],molecule=mol,return_wfn=True);energy=float(wfn.energy());g=np.array(gradient)
    psi4.core.flush_outfile();psi4.core.clean();native=(folder/'output.dat').read_text()
    residuals=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)]
    assert residuals and max(residuals)<=p['options']['solver_convergence'] and np.isfinite(g).all() and np.isfinite(energy)
    save(folder/'result.json',dict(energy_hartree=energy,gradient_au=g.tolist(),input=c['input'],native=source(folder/'output.dat'),plan=source(ROOT/'plan.json')))


def run():
    p=validate();start=time.monotonic();results={}
    with (ROOT/'started.json').open('x') as f:f.write('{}\n')
    for c in p['cases']:
        remaining=min(p['wall_seconds']-(time.monotonic()-start),read(checked(p['campaign']))['deadline_epoch']-time.time())
        if remaining<=0:raise RuntimeError('Frozen time cap reached')
        with (ROOT/c['label']/'worker.log').open('x') as log:
            subprocess.run([sys.executable,str(ROOT/'worker.py'),'case',c['label']],cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=remaining,check=True)
        results[c['label']]=read(ROOT/c['label']/'result.json')
        save(ROOT/'progress.json',dict(completed=list(results),total=8))
    curves=[]
    for b in p['basins']:
        values=[]
        for h in [.02,.04]:
            ep=results[f"{b['label']}-{h:+.2f}"]['energy_hartree'];em=results[f"{b['label']}-{-h:+.2f}"]['energy_hartree']
            values.append((ep+em-2*b['energy'])/(h*h))
        relative=abs(values[0]-values[1])/max(abs(values[0]),abs(values[1]),1e-20)
        curves.append(dict(basin=b['label'],curvatures_hartree_per_bohr2=values,step_halving_relative_difference=relative,
            directional_check_passed=min(values)>0 and relative<=.1))
    save(ROOT/'assessment.json',dict(at=now(),curves=curves,all_directional_checks_passed=all(c['directional_check_passed'] for c in curves),
        claim=p['claim'],minimum_certified=False,simulation_ready=False,requires_native_audit=True))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','case']);p.add_argument('label',nargs='?');a=p.parse_args()
    if a.action=='case':case(a.label)
    else:globals()[a.action]()
