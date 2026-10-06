"""Bounded Sella/Psi4 comparison of exposed cis-anti conformations.

This is diagnostic reference acquisition, not a fit or prospective validation.
Historical ledgers and source geometries remain immutable.
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
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, FORCE_FACTOR, HARTREE_EV, save, now, projected_metrics,
    geometry_audit, force_pass, xyz_text, review,
)

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-competing-recovery-v3-20261003'
CAMPAIGN = ART / 'cpd-anti-readiness-v3-20261003'


def validate():
    reg=read(ROOT/'registration.json');master=read(checked(reg['plan']))
    for pin in read(checked(reg['inputs']))['files']+master['sources']+master['runtime_sources']:
        checked(pin)
    for name,version in master['versions'].items():
        if metadata.version(name)!=version:raise RuntimeError('Runtime changed')
    if time.time()>=master['deadline_epoch']:raise RuntimeError('Original batch deadline reached')
    assert len(master['tasks'])==2 and master['max_new_gradients']==46
    return master


def run():
    master=validate();records=[]
    with (ROOT/'started.json').open('x') as f:json.dump(dict(at=now()),f)
    for task in master['tasks']:
        folder=Path(task['folder']);plan=read(checked(task['plan']))
        remaining=min(master['deadline_epoch'],plan['original_case_deadline'])-time.time()
        if remaining<=0:
            records.append(dict(case=folder.name,passed=False,error='Original deadline reached'));continue
        try:
            with (folder/'worker.log').open('x') as log:
                p=subprocess.run([sys.executable,str(ROOT/'worker.py'),'case',str(folder)],cwd=REPO,
                    stdout=log,stderr=subprocess.STDOUT,timeout=remaining)
            a=read(folder/'assessment.json') if (folder/'assessment.json').exists() else {}
            r=read(folder/'independent_review.json') if (folder/'independent_review.json').exists() else {}
            row=dict(case=folder.name,returncode=p.returncode,passed=bool(p.returncode==0 and a.get('joint_optimizer_converged') and r.get('independent_stationarity_passed')))
        except subprocess.TimeoutExpired:
            row=dict(case=folder.name,passed=False,error='Original deadline reached')
        records.append(row);save(ROOT/'progress.json',dict(records=records,total=2,at=now()))
    passed=len(records)==2 and all(r['passed'] for r in records)
    save(ROOT/'assessment.json',dict(records=records,recovered_cases_stationary=passed,minimum_certified=False,simulation_ready=False))
    if not passed:raise RuntimeError('Recovery incomplete; original caps unchanged')


def run_case(folder):
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    import psi4
    master = validate(); plan = read(folder/'plan.json'); replay_only=os.environ.get('CPD_REPLAY_ONLY')=='1'
    cache=read(checked(plan['cached_progress']))['evaluations']
    assert any(checked(t['replay_plan' if replay_only else 'plan']) == (folder/'plan.json').resolve() for t in master['tasks'])
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
            if attempts >= 40 or time.time() >= min(master['deadline_epoch'],plan['original_case_deadline']):
                raise RuntimeError('Diagnostic gradient/time cap reached; no continuation')
            x=self.atoms.positions/BOHR; audit=geometry_audit(x,plan,graph)
            if not audit['chemistry_passed']:
                save(folder/'rejected_trial.json',dict(geometry_bohr=x.tolist(),audit=audit))
                raise RuntimeError('Trial chemistry screen failed before QM')
            if len(rows)<len(cache):
                old=cache[len(rows)];result=read(checked(old['result']))
                expected=np.load(checked(result['geometry']))
                difference=float(np.max(abs(expected-x)))
                if difference>1e-10:raise RuntimeError('Saved Sella prefix diverged; no fresh restart')
                attempts+=1;rows.append(old)
                save(folder/'progress.json',dict(evaluations=rows,attempts=attempts,replayed=len(rows),new_gradients=0,minimum_certified=False))
                self.results=dict(energy=result['energy']*HARTREE_EV,forces=-np.array(result['gradient'])*FORCE_FACTOR)
                return
            if attempts==len(cache):
                expected=np.load(checked(plan['interrupted_geometry']))
                difference=float(np.max(abs(expected-x)))
                if difference>1e-10:raise RuntimeError('Interrupted Sella geometry not reproduced')
                save(folder/'prefix_replay_verified.json',dict(at=now(),cached_gradients=len(cache),
                    next_coordinate_difference_bohr=difference,new_qm_evaluations=0))
                if replay_only:raise RuntimeError('Replay-only preflight reached interrupted geometry; zero new QM')
                attempts=plan['original_attempted_gradients']
            if attempts>=40:raise RuntimeError('Original total attempt cap reached')
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
            (folder/'last_evaluated.xyz').write_text(xyz_text(plan['elements'],x,'Evaluated diagnostic target; not a certified minimum'))
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
            (folder/'optimized.xyz').write_text(xyz_text(plan['elements'],atoms.positions/BOHR,'Diagnostic constrained stationary candidate; no Hessian certification'))
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

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','case','validate']);parser.add_argument('folder',nargs='?',type=Path)
    args=parser.parse_args()
    if args.action=='case':run_case(args.folder.resolve())
    else:globals()[args.action]()
