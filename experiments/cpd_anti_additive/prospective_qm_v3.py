"""Register a fixed candidate, then acquire four prescribed prospective QM points.

No fitting or MM target scoring here. Existing Sella/Psi4 numerical conventions
are retained; candidate registration blocks further fitting before target exposure.
"""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.preliminary_protocol import POLICY, PAUSE
from experiments.cpd_anti_additive.readiness_fit_protocol_v3 import STATE, require_fit_ready
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, FORCE_FACTOR, HARTREE_EV, save, now, projected_metrics, geometry_audit,
    force_pass, xyz_text, review,
)
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART = REPO/'.development-artifacts'
ROOT = ART/'cpd-anti-prospective-qm-v3-r1'
FIT = ART/'cpd-anti-readiness-fit-v3-r1/model-048'
LOCK = STATE/'conformational_candidate_lock.json'
REFERENCES = ['endpoint-1-reference','endpoint-2-reference-lower-mm-basin']


def seed_at_offset(point, offset):
    """Rotate the graph-defined sugar component around the existing N1-C1 bond."""
    x = np.array(point['geometry_bohr'])
    graph = read(checked(point['record']['model_graph']))
    names = [a['key'] for a in graph['atoms']]
    endpoint = point['endpoint']
    c1, n1 = names.index(f"{endpoint}:C1'"), names.index(f'{endpoint}:N1')
    adjacent = {i:[] for i in range(len(x))}
    for b in graph['bonds']:
        a,c = b['indices']
        if {a,c} != {c1,n1}:
            adjacent[a].append(c); adjacent[c].append(a)
    move = {c1}; todo = [c1]
    while todo:
        i = todo.pop()
        for j in adjacent[i]:
            if j not in move:
                move.add(j); todo.append(j)
    expected = {i for i,n in enumerate(names) if n.startswith(f'{endpoint}:') and "'" in n}
    assert move == expected and len(move) == 17 and n1 not in move
    indices = point['record']['torsion_indices']
    reference = _dihedral_degrees(*x[indices])
    target = (reference+offset+180)%360-180
    axis = x[c1]-x[n1]; axis /= np.linalg.norm(axis); ids = sorted(move)
    candidates = []
    for theta in [np.radians(offset),-np.radians(offset)]:
        v = x[ids]-x[n1]; y = x.copy()
        y[ids] = x[n1]+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta))
        error = abs((_dihedral_degrees(*y[indices])-target+180)%360-180)
        candidates.append((error,y))
    error,y = min(candidates,key=lambda v:v[0]); assert error < 1e-8
    assert np.array_equal(y[[i for i in range(len(x)) if i not in move]],x[[i for i in range(len(x)) if i not in move]])
    return y,target,ids

def validate():
    assert not read(PAUSE)['paused']
    registration=read(ROOT/'registration.json');lock=read(checked(registration['candidate_lock']))
    plan=read(checked(lock['validation_plan']))
    for row in read(checked(lock['validation_inputs']))['files']+plan['sources']+plan['runtime_sources']:
        checked(row)
    assert lock['candidate']==plan['candidate'] and lock['further_fitting_blocked']
    assert plan['max_total_new_gradients']==160 and len(plan['tasks'])==4 and plan['max_continuations']==0
    assert time.time()<read(checked(plan['campaign']))['deadline_epoch']
    for name,version in plan['versions'].items():assert metadata.version(name)==version
    return plan


def run_case(folder):
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    import psi4
    master = validate(); plan = read(folder/'plan.json')
    assert any(checked(t['plan']) == (folder/'plan.json').resolve() for t in master['tasks'])
    assert psi4.__version__ == plan['psi4_version']
    with (folder/'started.json').open('x') as f:
        json.dump(dict(at=now(),plan=source(folder/'plan.json'),registration=source(ROOT/'registration.json')),f)
    os.chdir(folder)
    graph = read(checked(plan['record']['model_graph']))
    scratch = Path(plan['scratch_dir']); scratch.mkdir(parents=True,exist_ok=False)
    assert shutil.disk_usage(scratch).free > 15*1024**3
    psi4.set_num_threads(plan['threads']);psi4.set_memory('6 GiB')
    psi4.core.IOManager.shared_object().set_default_path(str(scratch));psi4.set_options(plan['options'])
    rows=[];convergence=[];attempts=0;started=time.monotonic()
    save(folder/'progress.json',dict(evaluations=rows,attempts=0,minimum_certified=False))
    class Psi4Calculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=('energy','forces'),system_changes=all_changes):
            nonlocal attempts
            super().calculate(atoms,properties,system_changes)
            if attempts >= 40 or time.monotonic()-started >= plan['wall_seconds']:
                raise RuntimeError('Prospective point gradient/time cap reached; no continuation')
            x=self.atoms.positions/BOHR; audit=geometry_audit(x,plan,graph)
            if not audit['chemistry_passed']:
                save(folder/'rejected_trial.json',dict(geometry_bohr=x.tolist(),audit=audit))
                raise RuntimeError('Trial chemistry screen failed before QM')
            attempts+=1;out=folder/f'evaluation-{attempts:03d}';out.mkdir()
            np.save(out/'geometry_bohr.npy',x)
            save(out/'input.json',dict(elements=plan['elements'],geometry_bohr=x.tolist(),method=plan['method'],
                options=plan['options'],charge=0,multiplicity=1,attempt=attempts,started_at=now(),geometry_audit=audit))
            psi4.set_output_file(str(out/'output.dat'),False)
            text='\n'.join(el+' '+' '.join(f'{v:.15f}' for v in pos) for el,pos in zip(plan['elements'],x))
            molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
            tick=time.monotonic(); gradient,wfn=psi4.gradient(plan['method'],molecule=molecule,return_wfn=True)
            energy=float(wfn.energy());gradient=np.array(gradient)
            assert np.max(abs(np.array(wfn.molecule().geometry())-x)) < 1e-10
            psi4.core.flush_outfile();psi4.core.clean()
            native=(out/'output.dat').read_text()
            residuals=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)]
            assert residuals and max(residuals) <= plan['options']['solver_convergence']
            assert gradient.shape == x.shape and np.isfinite(gradient).all() and np.isfinite(energy)
            metrics=projected_metrics(x,gradient,plan['record']['torsion_indices'])
            save(out/'result.json',dict(energy=energy,gradient=gradient.tolist(),input=source(out/'input.json'),
                geometry=source(out/'geometry_bohr.npy'),native=source(out/'output.dat'),reused=False,audit=audit,
                independent_projection=metrics,elapsed_seconds=time.monotonic()-tick))
            rows.append(dict(result=source(out/'result.json'),energy=energy,**metrics))
            save(folder/'progress.json',dict(evaluations=rows,attempts=attempts,elapsed_seconds=time.monotonic()-started,minimum_certified=False))
            (folder/'last_evaluated.xyz').write_text(xyz_text(plan['elements'],x,'Evaluated prospective target; not a certified minimum'))
            self.results=dict(energy=energy*HARTREE_EV,forces=-gradient*FORCE_FACTOR)
            print(json.dumps(dict(case=folder.name,evaluation=attempts,energy=energy,**metrics)),flush=True)
    atoms=Atoms(plan['elements'],positions=np.array(plan['geometry_bohr'])*BOHR);atoms.calc=Psi4Calculator()
    constraint=Constraints(atoms);constraint.fix_dihedral(tuple(plan['record']['torsion_indices']))
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces));x=atoms.positions/BOHR
            metrics=projected_metrics(x,-atoms.get_forces(apply_constraint=False)/FORCE_FACTOR,plan['record']['torsion_indices'])
            audit=geometry_audit(x,plan,graph)
            passed=force_pass(metrics,plan['limits']) and audit['constraint_passed'] and audit['chemistry_passed']
            convergence.append(dict(native_converged=native,independent_passed=passed,evaluations=attempts,
                **metrics,torsion_error_deg=audit['torsion_error_deg']))
            save(folder/'convergence_checks.json',convergence)
            return native and passed
    native=False;error=None
    try:
        optimizer=AuditedSella(atoms,constraints=constraint,logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'),**plan['optimizer'])
        native=bool(optimizer.run(fmax=plan['limits']['max_gradient']*FORCE_FACTOR,steps=40))
        if native:
            (folder/'optimized.xyz').write_text(xyz_text(plan['elements'],atoms.positions/BOHR,'Prospective constrained stationary candidate; no Hessian certification'))
        else:error='Sella step cap reached without joint convergence'
    except Exception as exc:
        error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
    finally:
        psi4.core.flush_outfile();psi4.core.clean()
        save(folder/'assessment.json',dict(joint_optimizer_converged=native,error=error,evaluations=len(rows),
            attempted_gradients=attempts,finished_at=now(),elapsed_seconds=time.monotonic()-started,minimum_certified=False,simulation_ready=False))
    independent=review(folder)
    if not native or not independent.get('independent_stationarity_passed'):
        raise RuntimeError(error or 'Independent stationarity review failed')

def run():
    plan=validate();start=time.monotonic();records=[]
    with (ROOT/'started.json').open('x') as f:
        json.dump(dict(at=now(),registration=source(ROOT/'registration.json')),f)
    for task in plan['tasks']:
        folder=Path(task['folder']);remaining=min(plan['hard_seconds']-(time.monotonic()-start),read(checked(plan['campaign']))['deadline_epoch']-time.time())
        if remaining <= 0:
            records.append(dict(case=task['case_id'],state='not_started_total_time_cap',passed=False));continue
        try:
            with (folder/'worker.log').open('w') as log:
                p=subprocess.run([sys.executable,str(ROOT/'worker.py'),'case',str(folder)],cwd=REPO,stdout=log,
                    stderr=subprocess.STDOUT,timeout=min(plan['per_case_hard_seconds'],remaining))
            result=read(folder/'assessment.json') if (folder/'assessment.json').exists() else None
            audit=read(folder/'independent_review.json') if (folder/'independent_review.json').exists() else None
            passed=bool(p.returncode == 0 and result and result['joint_optimizer_converged'] and audit and audit.get('independent_stationarity_passed'))
            row=dict(case=task['case_id'],returncode=p.returncode,passed=passed,
                assessment=source(folder/'assessment.json') if result else None,
                independent_review=source(folder/'independent_review.json') if audit else None)
        except subprocess.TimeoutExpired:
            row=dict(case=task['case_id'],passed=False,error='Frozen wall-time cap reached; partial native outputs retained')
            save(folder/'timeout.json',dict(at=now(),**row))
        records.append(row);save(ROOT/'progress.json',dict(at=now(),records=records,total=4))
    passed=all(r['passed'] for r in records) and len(records)==4
    save(ROOT/'assessment.json',dict(at=now(),records=records,all_four_constrained_stationarity_passed=passed,
        candidate_lock=source(LOCK),elapsed_seconds=time.monotonic()-start,MM_prospective_validation_complete=False,
        minimum_certified=False,preliminary_research_qualified=False,simulation_ready=False))
    if not passed:raise RuntimeError('Prospective acquisition incomplete/failed; no continuation or target omission')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','case','validate']);p.add_argument('folder',nargs='?',type=Path);a=p.parse_args()
    if a.action=='case':run_case(a.folder.resolve())
    else:globals()[a.action]()
