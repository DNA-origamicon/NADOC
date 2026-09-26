"""Local torsion residual interpolation with held-out midpoint checks; no promotion."""
import json,sys,math
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import source,write
ART=REPO/'.development-artifacts'

def run(root):
    from experiments.cpd_anti_additive.validation_gate import require_fit_ready
    require_fit_ready()
    root.mkdir(exist_ok=False);base=ART/'cpd-anti-matched-mm-v1';plan=json.loads((base/'plan.json').read_text());assessment=json.loads((base/'assessment.json').read_text());rows=[];points={p['label']:p for p in plan['points']};sources=[source(base/'assessment.json')]
    for r in assessment['comparisons']:rows.append(dict(r,endpoint=int(r['point'].split('-')[1]),role='train'))
    for name in ('cpd-anti-matched-half-mm-v1','cpd-anti-matched-half-mm-v2'):
        folder=ART/name;review=json.loads((folder/'independent_review.json').read_text());pp=json.loads((folder/'plan.json').read_text());points.update({t['point']['label']:t['point'] for t in pp['tasks']});aa=json.loads((folder/'assessment.json').read_text());assert len(review['records'])==len(aa['records']);sources.extend([source(folder/'assessment.json'),source(folder/'independent_review.json')])
        for r in aa['records']:
            assert r['converged'];rows.append(dict(candidate=r['candidate'],point=r['point'],endpoint=r['endpoint'],qm_relative_kcal_mol=r['qm_relative_kcal_mol'],mm_relaxed_relative_kcal_mol=r['mm_relative_kcal_mol'],error_kcal_mol=r['error_kcal_mol'],role='held_out'))
    for r in rows:
        ref=points[f"endpoint-{r['endpoint']}-reference"]['record']['target_degrees'];target=points[r['point']]['record']['target_degrees'];r['actual_delta_radians']=math.radians((target-ref+180)%360-180)
    fits=[]
    for c in plan['candidates']:
        for e in (1,2):
            subset=[r for r in rows if r['candidate']==c['label'] and r['endpoint']==e];train=[r for r in subset if r['role']=='train'];test=[r for r in subset if r['role']=='held_out'];assert len(train)==len(test)==2
            def basis(r):
                t=r['actual_delta_radians'];return [math.cos(t)-1,math.sin(t)]
            coeff=np.linalg.solve(np.array([basis(r) for r in train]),-np.array([r['error_kcal_mol'] for r in train]));tests=[]
            for r in test:
                correction=float(np.dot(basis(r),coeff));tests.append(dict(point=r['point'],uncorrected_error=r['error_kcal_mol'],predicted_correction=correction,corrected_error=r['error_kcal_mol']+correction))
            fits.append(dict(candidate=c['label'],endpoint=e,cos_coefficient_kcal_mol=float(coeff[0]),sin_coefficient_kcal_mol=float(coeff[1]),reference_torque_kcal_mol_rad=float(coeff[1]),global_peak_to_peak_kcal_mol=float(2*np.linalg.norm(coeff)),held_out=tests))
    write(root/'assessment.json',dict(profile=rows,diagnostic_fits=fits,sources=sources,correction_form='a*(cos(delta)-1)+b*sin(delta), delta is actual constrained dihedral relative to reference',scope='Two outer angles train; two midpoint angles held out. Local residual diagnostic only; not transferable torsion parameters. Nonzero reference torque changes equilibrium and requires coupled geometry validation. Narrow angular coverage cannot constrain global periodic behavior.',minimum_certified=False,simulation_ready=False))
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    for f in fits:print(f['candidate'],f['endpoint'],'heldout',[round(t['corrected_error'],4) for t in f['held_out']],'reference torque',round(f['reference_torque_kcal_mol_rad'],3),'global range',round(f['global_peak_to_peak_kcal_mol'],2))

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
