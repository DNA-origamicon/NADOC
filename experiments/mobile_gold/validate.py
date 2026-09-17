"""GPU-only native mechanics, restart, sampling and throughput qualification."""
from __future__ import annotations
import argparse, json, math, subprocess, time
from pathlib import Path
import numpy as np
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.physics.oxdna_mobile_gold import find_mobile_gold_oxdna


def run_case(root, name, xyz, *, cores, grafts=(), steps=1, dt=1e-4, thermostat='no', seed=123, edge=True, precision='mixed', binary=None, k=100., clearance=.4, initial=None, sample=100, coating=()):
    d=root/name; d.mkdir(parents=True,exist_ok=False)
    xyz=np.asarray(xyz,float); n=len(xyz); nc=len(cores); nd=n-nc
    (d/'topology.top').write_text(f'{n} {n}\n'+''.join(f'{i+1} {"A" if i<nd else "499"} -1 -1\n' for i in range(n)))
    if initial is None:
        rows=np.zeros((n,15));rows[:,:3]=xyz;rows[:,3]=1;rows[:,8]=1
        (d/'conf.dat').write_text('t = 0\nb = 200 200 200\nE = 0 0 0\n'+'\n'.join(' '.join(map(str,r)) for r in rows)+'\n')
    else: (d/'conf.dat').write_text(Path(initial).read_text())
    lines=[f'{nd} {nc} {len(grafts)} {clearance} {k}']
    for j,c in enumerate(cores):
        radius,mass,inertia,diff,drot=c
        lines.append(f'{nd+j} {radius} {mass} {inertia} {diff} {drot}')
    lines += [' '.join(map(str,g)) for g in grafts]
    if coating:
        lines.append(f'COATING_V1 {len(coating)}')
        lines += [' '.join(map(str,c)) for c in coating]
    (d/'mobile_gold.dat').write_text('\n'.join(lines)+'\n')
    spec=OxdnaStageSpec(name,'production','MD',steps,'CUDA',dt=dt,thermostat=thermostat,diff_coeff=2.5,refresh_vel=False,interaction='DNA2GOLD',gold_file='mobile_gold.dat',seed=seed,print_conf_interval_override=sample,print_energy_every_override=sample)
    text=render_stage_input(spec,'topology.top','conf.dat').replace('use_edge = true',f'use_edge = {str(edge).lower()}').replace('backend_precision = mixed',f'backend_precision = {precision}')
    (d/'input').write_text(text+'\ntrajectory_print_momenta = true\n')
    start=time.perf_counter()
    with (d/'run.log').open('w') as log:
        proc=subprocess.run([binary or find_mobile_gold_oxdna(),'input'],cwd=d,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    elapsed=time.perf_counter()-start
    if proc.returncode: raise RuntimeError(f'{name}: '+(d/'run.log').read_text()[-2500:])
    final=np.loadtxt(d/'last_conf.dat',skiprows=3)
    if not np.isfinite(final).all(): raise AssertionError(f'{name}: nonfinite trajectory')
    return final,dict(name=name,steps=steps,wall_s=elapsed,steps_per_s=steps/elapsed,directory=str(d))


def mechanics(root,binary=None):
    records=[]; dt=1e-4
    # Nonradial linker force tests BOTH nucleotide torque and core torque.
    core=(3.,100.,360.,.01,.0008)
    dna=np.array([4.5, .6,0]); back=np.array([-.34,.3408,0]); site=np.array([3,0,0])
    delta=dna+back-site; length=np.linalg.norm(delta); force=-10*(length-.8)*delta/length
    td=np.cross(back,force); tc=np.cross(site,-force)
    for edge in (False,True):
        for precision in ('float','mixed'):
            final,record=run_case(root,f'graft_{edge}_{precision}',[dna,[0,0,0]],cores=[core],grafts=[(0,0,3,0,0,.8,10)],edge=edge,precision=precision,binary=binary,dt=dt)
            np.testing.assert_allclose(final[0,9:12]/dt,force,rtol=3e-4,atol=2e-4)
            np.testing.assert_allclose(final[1,9:12]/dt*100,-force,rtol=3e-4,atol=2e-4)
            np.testing.assert_allclose(final[0,12:15]/dt,td,rtol=3e-4,atol=2e-4)
            np.testing.assert_allclose(final[1,12:15]/dt*360,tc,rtol=3e-4,atol=2e-4)
            record.update(force_error=float(np.linalg.norm(final[0,9:12]/dt-force)),reciprocal_error=float(np.linalg.norm(final[0,9:12]+100*final[1,9:12])/dt),core_torque_error=float(np.linalg.norm(final[1,12:15]/dt*360-tc)))
            records.append(record)
    final,rec=run_case(root,'dna_exclusion',[[3.3,0,0],[0,0,0]],cores=[core],binary=binary,dt=dt)
    np.testing.assert_allclose(final[0,9]/dt,10,rtol=.001)
    np.testing.assert_allclose(final[1,9]/dt*100,-10,rtol=.001)
    records.append(rec)
    final,rec=run_case(root,'core_exclusion',[[50,50,50],[0,0,0],[5.9,0,0]],cores=[core,core],binary=binary,dt=dt)
    np.testing.assert_allclose(final[1:,9]/dt*100,[-10,10],rtol=.002);records.append(rec)
    # Split NVE trajectory must match uninterrupted run including core orientation.
    args=dict(cores=[core],grafts=[(0,0,3,0,0,.8,10)],binary=binary,dt=.001)
    xyz=[dna,[0,0,0]]
    full,rec=run_case(root,'restart_full',xyz,steps=200,**args);records.append(rec)
    half,rec=run_case(root,'restart_half',xyz,steps=100,**args);records.append(rec)
    split,rec=run_case(root,'restart_split',xyz,steps=100,initial=root/'restart_half/last_conf.dat',**args);records.append(rec)
    np.testing.assert_allclose(split,full,atol=3e-6,rtol=3e-5)
    return records

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--binary');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    records=mechanics(a.output,a.binary)
    (a.output/'results.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(records,indent=2))
