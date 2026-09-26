"""Bounded Fourier residual fits with midpoint holdout and torque diagnostics."""
import json,sys,math
from pathlib import Path
import numpy as np
from scipy.optimize import lsq_linear
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import source,write
ART=REPO/'.development-artifacts'

def run(root):
    from experiments.cpd_anti_additive.validation_gate import require_fit_ready
    require_fit_ready()
    root.mkdir(exist_ok=False);local=ART/'cpd-anti-local-profile-diagnostic-v1/assessment.json';rows=json.loads(local.read_text())['profile'];outer=ART/'cpd-anti-matched-outer-mm-v1';plan=json.loads((outer/'plan.json').read_text());a=json.loads((outer/'assessment.json').read_text());refplan=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text())
    for r in a['records']:
        p=next(t['point'] for t in plan['tasks'] if t['point']['label']==r['point']);ref=next(p for p in refplan['points'] if p['label']==f"endpoint-{r['endpoint']}-reference");delta=math.radians((p['record']['target_degrees']-ref['record']['target_degrees']+180)%360-180);rows.append(dict(candidate=r['candidate'],endpoint=r['endpoint'],point=r['point'],actual_delta_radians=delta,error_kcal_mol=r['error_kcal_mol'],role='train'))
    fits=[]
    for candidate in sorted({r['candidate'] for r in rows}):
        for e in (1,2):
            subset=[r for r in rows if r['candidate']==candidate and r['endpoint']==e];train=[r for r in subset if r['role']=='train'];test=[r for r in subset if r['role']=='held_out'];assert len(train)==4 and len(test)==2
            for mode in ('free_torque','zero_reference_torque'):
                def basis(t):
                    return [math.cos(t)-1,math.cos(2*t)-1,math.sin(t),math.sin(2*t)] if mode=='free_torque' else [math.cos(t)-1,math.cos(2*t)-1,math.sin(2*t)-2*math.sin(t)]
                X=np.array([basis(r['actual_delta_radians']) for r in train]);y=-np.array([r['error_kcal_mol'] for r in train]);penalty=np.eye(X.shape[1]);penalty[-1,-1]=math.sqrt(5) if mode=='zero_reference_torque' else 1
                for ridge in (.0001,.01,.1):
                    result=lsq_linear(np.vstack([X,math.sqrt(ridge)*penalty]),np.r_[y,np.zeros(X.shape[1])],bounds=(-10,10),tol=1e-12);assert result.success;coef=result.x
                    fourier=coef if mode=='free_torque' else np.array([coef[0],coef[1],-2*coef[2],coef[2]])
                    tests=[dict(point=r['point'],corrected_error_kcal_mol=float(r['error_kcal_mol']+np.dot(basis(r['actual_delta_radians']),coef))) for r in test];training=X@coef-y;grid=np.linspace(-math.pi,math.pi,1441);values=np.array([np.dot(basis(t),coef) for t in grid])
                    fits.append(dict(candidate=candidate,endpoint=e,mode=mode,ridge=ridge,coefficients=fourier.tolist(),training_rmse=float(np.sqrt(np.mean(training**2))),held_out=tests,reference_torque_kcal_mol_rad=float(fourier[2]+2*fourier[3]),reference_curvature_kcal_mol_rad2=float(-fourier[0]-4*fourier[1]),global_peak_to_peak_kcal_mol=float(np.ptp(values))))
    write(root/'assessment.json',dict(fits=fits,sources=[source(local),source(outer/'assessment.json'),source(outer/'independent_review.json')],scope='Exploratory n=1,2 Fourier corrections; fit ±15/±30, hold out ±7.5; predeclared ridge sweep and ±10 coefficient bounds (zero-torque transformed sin1 can reach20). No candidate accepted by held-out tuning. Equilibrium stability and export unvalidated.',minimum_certified=False,simulation_ready=False));(root/'executed_source.py').write_text(Path(__file__).read_text())
    for f in fits:
        if f['candidate']=='baseline':print(f['endpoint'],f['mode'],f['ridge'],'train',round(f['training_rmse'],3),'holdout',[round(t['corrected_error_kcal_mol'],3) for t in f['held_out']],'torque',round(f['reference_torque_kcal_mol_rad'],3),'curv',round(f['reference_curvature_kcal_mol_rad2'],3))

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
