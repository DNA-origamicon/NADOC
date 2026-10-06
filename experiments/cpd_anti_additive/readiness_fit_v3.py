"""Bounded gate-directed v3 fit with an added, independently checked QM branch.

Uses fresh finite-difference sensitivities, isolated Sella processes and unchanged
22 coefficient bounds. All historical cases and the new branch must pass.
"""
import argparse
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np
from scipy.optimize import minimize
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive import shape_fit_v2 as frozen
from experiments.cpd_anti_additive.readiness_fit_protocol_v3 import STATE,require_fit_ready,begin_round
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now,BOHR
ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-readiness-fit-v3-r1'


def validate():
    _,plan=require_fit_ready(stage='conformational')
    return plan,plan


def assemble(folder,number,v,plan,results,coordinates,psfs):
    points=read(checked(plan['points']));reps=read(checked(plan['representatives']));n=len(points)
    assert len(results)==len(coordinates)==n+len(reps)
    errors=frozen.relative([r['energy_kcal'] for r in results[:n]],points)-np.array([p['qm_relative_kcal_mol'] for p in points])
    residual=list(errors/math.sqrt(n))
    for p,x in zip(points,coordinates):
        residual.extend(frozen.aligned_residual(np.array(p['geometry_bohr'])*BOHR,x,p['elements'])/(.25*math.sqrt(n)))
    residual.extend(r['branch_descriptors']['basin_max_torsion_deg']/(20*math.sqrt(n)) for r in results[:n])
    geom=[frozen.representative_geometry(psfs[p['endpoint']],p['atom_map'],np.array(p['geometry_bohr'])*BOHR,x) for p,x in zip(reps,coordinates[n:])]
    residual.extend(g['max_bond_A']/(.03*math.sqrt(3)) for g in geom)
    residual.extend(g['max_angle_deg']/(3*math.sqrt(3)) for g in geom)
    residual.extend(math.sqrt(.05/len(v))*v/3)
    residual.extend(0. if r['independent_stationarity_and_chemistry_passed'] else 1000. for r in results)
    residual=np.array(residual);assert np.isfinite(residual).all()
    valid=all(r['independent_stationarity_and_chemistry_passed'] for r in results)
    energy=dict(rmse_kcal=float(np.sqrt(np.mean(errors**2))),max_abs_kcal=float(abs(errors).max()))
    energy['legacy23_rmse_kcal']=float(np.sqrt(np.mean(errors[:23]**2)))
    energy['passed']=energy['rmse_kcal']<=1 and energy['legacy23_rmse_kcal']<=1 and energy['max_abs_kcal']<=2
    report=dict(at=now(),number=number,candidate=source(folder/'candidate.prm'),parameters=v.tolist(),
        objective=float(residual@residual),numerically_valid=valid,energy=energy,
        shape_failures=[r['case_id'] for r in results[:n] if not r['branch_descriptor_match']],
        representative_geometry=geom,results=results,
        development_parameter_passed=valid and energy['passed'] and all(r['branch_descriptor_match'] for r in results[:n]) and all(g['passed'] for g in geom),
        minimum_certified=False,simulation_ready=False)
    return report,residual

def layout(points):
    n = len(points)
    blocks = [slice(0, n)]
    cursor = n
    for p in points:
        length = 3 * sum(e != "H" for e in p["elements"])
        blocks.append(slice(cursor, cursor + length))
        cursor += length
    return blocks, slice(cursor, cursor + n), slice(cursor + n, cursor + n + 6)

def gate_values(r, blocks, torsions, reps):
    """Ratios to the existing gates; all ratios <= 1 is linearized feasibility."""
    n = blocks[0].stop
    energy = r[blocks[0]] * math.sqrt(n)
    shapes = [np.linalg.norm(r[b]) * math.sqrt(n) for b in blocks[1:]]
    return np.r_[np.linalg.norm(energy) / math.sqrt(n), np.linalg.norm(energy[:23])/math.sqrt(23), abs(energy) / 2,
                 shapes, abs(r[torsions]) * math.sqrt(n),
                 abs(r[reps]) * math.sqrt(3)]

def propose(r, jac, x, radius, blocks, torsions, reps):
    """Convex epigraph problem using squared norms and analytic derivatives."""
    n = blocks[0].stop
    norm_blocks = [(blocks[0], 1.), (slice(0,23), n/23.)] + [(b, float(n)) for b in blocks[1:]]
    scalar_ids = np.r_[np.arange(n), np.arange(torsions.start, torsions.stop),
                       np.arange(reps.start, reps.stop)]
    scales = np.r_[np.full(n, math.sqrt(n) / 2),
                   np.full(n, math.sqrt(n)), np.full(6, math.sqrt(3))]

    def constraints(z):
        v = r + jac @ z[:-1]
        norms = [z[-1] - scale * (v[b] @ v[b]) for b, scale in norm_blocks]
        return np.r_[norms, z[-1] - (v[scalar_ids] * scales) ** 2]

    def derivative(z):
        v = r + jac @ z[:-1]
        rows = [-2 * scale * (v[b] @ jac[b]) for b, scale in norm_blocks]
        rows.extend(-2 * v[scalar_ids, None] * scales[:, None] ** 2 * jac[scalar_ids])
        return np.c_[np.array(rows), np.ones(len(rows))]

    z0 = np.r_[np.zeros(len(x)), max(gate_values(r, blocks, torsions, reps)) ** 2]
    result = minimize(lambda z: z[-1] + 1e-8 * (z[:-1] @ z[:-1]), z0,
                      jac=lambda z: np.r_[2e-8 * z[:-1], 1.], method="SLSQP",
                      bounds=list(zip(np.maximum(-radius, -5 - x),
                                      np.minimum(radius, 5 - x))) + [(0, None)],
                      constraints=[dict(type="ineq", fun=constraints, jac=derivative)],
                      options=dict(maxiter=400, ftol=1e-10))
    v = r + jac @ result.x[:-1]
    return dict(radius_kcal=radius, success=bool(result.success), message=result.message,
                iterations=result.nit, minimum_constraint_slack=float(min(constraints(result.x))),
                predicted_max_gate_ratio=float(max(gate_values(v, blocks, torsions, reps))),
                predicted_objective=float(v @ v), parameters=(x + result.x[:-1]).tolist(),
                step=result.x[:-1].tolist(), predicted_shapes_A=[float(np.linalg.norm(v[b]) * .25 * math.sqrt(n)) for b in blocks[1:]],
                nonlinear_feasibility_established=False)

def child(path):
    from openmm import app
    receipt, plan = validate()
    request = read(path)
    folder = path.parent
    assert folder.parent.resolve() == ROOT.resolve()
    parameters = np.array(request["parameters"])
    assert parameters.shape == (22,) and np.max(abs(parameters)) <= 5 + 1e-12
    frozen.export_parameters(checked(plan["baseline_parameters"]), folder / "candidate.prm", plan["variables"], parameters)
    par = frozen.parameters(folder / "candidate.prm")
    points = read(checked(plan["points"])) + read(checked(plan["representatives"]))
    psfs = {p["endpoint"]: app.CharmmPsfFile(str(Path(plan["parent"]) / f"endpoint-{p['endpoint']}" / "fragment.psf")) for p in points}
    systems = {e: psf.createSystem(par, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False) for e, psf in psfs.items()}
    deadline = time.monotonic() + max(0., request["deadline_epoch"] - time.time())
    results, coordinates = [], []
    for p in points:
        if time.monotonic() >= deadline:
            raise RuntimeError("Declared wall limit reached")
        result, x = frozen.relax_point(folder / p["case_id"], p, systems[p["endpoint"]], plan, deadline)
        results.append(result)
        coordinates.append(x)
        save(folder / "progress.json", results)
    report, residual = assemble(folder, request["number"], parameters, plan, results, coordinates, psfs)
    np.save(folder / "residual.npy", residual)
    save(folder / "assessment.json", report)

class FitStop(RuntimeError):pass


def run():
    _,plan=validate()
    _,_,round_number=begin_round(ROOT)
    ROOT.mkdir(exist_ok=False);shutil.copyfile(checked(plan['worker']),ROOT/'worker.py')
    start=time.time();deadline=min(start+7200,read(checked(read(STATE/'lineage.json')['contract']))['deadline_epoch'])
    save(ROOT/'started.json',dict(at=now(),round=round_number,deadline_epoch=deadline,receipt=source(STATE/'receipt.json')))
    points=read(checked(plan['points']));blocks,torsions,reps=layout(points)
    history=[];best=None;cache={};termination=None
    def evaluate(x,label):
        nonlocal best
        x=np.asarray(x);key=x.tobytes()
        if key in cache:return cache[key]
        if time.time()>=deadline or len(history)>=240:raise FitStop('Frozen time/model cap reached')
        number=len(history)+1;folder=ROOT/f'model-{number:03d}';folder.mkdir()
        history.append(dict(number=number,state='started',purpose=label))
        request=dict(number=number,parameters=x.tolist(),deadline_epoch=deadline)
        save(folder/'request.json',request);save(ROOT/'progress.json',dict(history=history,best=best))
        with (folder/'native.log').open('x') as log:
            p=subprocess.run([sys.executable,str(ROOT/'worker.py'),'child',str(folder/'request.json')],cwd=REPO,
                stdout=log,stderr=subprocess.STDOUT,timeout=max(.01,deadline-time.time()))
        if p.returncode:raise FitStop('Native child failed; preserve all results')
        report=read(folder/'assessment.json');residual=np.load(folder/'residual.npy')
        score=float(max(gate_values(residual,blocks,torsions,reps)))
        row=dict(number=number,state='complete',purpose=label,score=score,assessment=source(folder/'assessment.json'),
            numerically_valid=report['numerically_valid'],development_parameter_passed=report['development_parameter_passed'])
        history[-1]=row
        if report['numerically_valid'] and (best is None or score<best['score']):best=row
        save(ROOT/'progress.json',dict(history=history,best=best))
        print(dict(model=number,purpose=label,max_gate=score,shapes=report['shape_failures'],passed=report['development_parameter_passed']),flush=True)
        cache[key]=(residual,score,report['numerically_valid'])
        if report['development_parameter_passed']:best=row;raise FitStop('First full development pass')
        return cache[key]
    try:
        x=np.array(plan['initial_parameters']);r,score,valid=evaluate(x,'initial24target')
        if not valid:raise FitStop('Initial model numerical failure')
        radius=.5
        while True:
            # Refresh all22 derivatives at the current center, rather than
            # extrapolating the old 23-target Jacobian across basin changes.
            cols=[]
            for j in range(22):
                v=x.copy();h=.02 if x[j]+.02<=5 else -.02;v[j]+=h
                rp,_,vp=evaluate(v,f'finite_difference_{j}')
                if not vp:raise FitStop('Invalid derivative model')
                cols.append((rp-r)/h)
            jac=np.array(cols).T
            for retry in range(4):
                proposal=propose(r,jac,x,radius,blocks,torsions,reps)
                if not proposal['success'] or proposal['minimum_constraint_slack'] < -1e-7:
                    raise FitStop('Local proposal failed; no hidden restart')
                trial=np.array(proposal['parameters']);step=trial-x
                if max(abs(step))<1e-7:raise FitStop('No resolvable improving step')
                observed,trial_score,valid=evaluate(trial,'gate_directed_step')
                if valid and trial_score<score:
                    expected=score-proposal['predicted_max_gate_ratio']
                    ratio=(score-trial_score)/max(expected,1e-12)
                    x,r,score=trial,observed,trial_score
                    radius=min(1.,radius*1.5) if ratio>.75 else radius
                    break
                radius*=.5
            else:raise FitStop('Four rejected trust steps; review model response')
    except (FitStop,subprocess.TimeoutExpired) as exc:
        termination=str(exc)
    except Exception as exc:
        termination=repr(exc);save(ROOT/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
    chosen=read(checked(best['assessment'])) if best else None
    save(ROOT/'assessment.json',dict(at=now(),round=round_number,termination=termination,history=history,selected=best,
        candidate=chosen['candidate'] if chosen else None,elapsed_seconds=time.time()-start,
        development_parameter_passed=bool(chosen and chosen['development_parameter_passed']),
        prospective_validation_complete=False,minimum_certified=False,simulation_ready=False))
    validate()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','child','validate']);p.add_argument('request',nargs='?',type=Path);a=p.parse_args()
    if a.action=='child':child(a.request)
    else:globals()[a.action]()
