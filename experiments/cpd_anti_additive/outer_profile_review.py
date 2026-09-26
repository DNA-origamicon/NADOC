"""Evaluate previously frozen local correction on outer-angle held-out data."""
import json,math,sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import source,checked,write
from backend.parameterization.photoproduct_qm import parse_xyz
ART=REPO/'.development-artifacts'

def run(root):
    root.mkdir(exist_ok=False);outer=ART/'cpd-anti-matched-outer-mm-v1';plan=json.loads((outer/'plan.json').read_text());a=json.loads((outer/'assessment.json').read_text());review=json.loads((outer/'independent_review.json').read_text());assert review['verified_constrained_cases']==16
    frozen=ART/'cpd-anti-local-profile-diagnostic-v1/assessment.json';fits=json.loads(frozen.read_text())['diagnostic_fits'];refplan=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text());records=[]
    for r in a['records']:
        assert r['converged'];t=next(t for t in plan['tasks'] if t['candidate']['label']==r['candidate'] and t['point']['label']==r['point']);p=t['point'];e=p['endpoint'];ref=next(p for p in refplan['points'] if p['label']==f'endpoint-{e}-reference');delta=math.radians((p['record']['target_degrees']-ref['record']['target_degrees']+180)%360-180);fit=next(f for f in fits if f['candidate']==r['candidate'] and f['endpoint']==e);correction=fit['cos_coefficient_kcal_mol']*(math.cos(delta)-1)+fit['sin_coefficient_kcal_mol']*math.sin(delta)
        sp=checked(t['candidate']['systems'][str(e)]);system=mm.XmlSerializer.deserialize(sp.read_text());labels=[]
        for i,f in enumerate(system.getForces()):f.setForceGroup(i);labels.append(type(f).__name__+':'+str(i))
        integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
        def energy_terms(path):
            atoms,_=parse_xyz(path.read_text());ctx.setPositions(np.array([v[1:] for v in atoms])*u.angstrom);return np.array([ctx.getState(getEnergy=True,groups=1<<i).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole) for i in range(len(labels))])
        xyz=outer/r['candidate']/r['point']/'optimized.xyz';refxyz=ART/'cpd-anti-matched-mm-v1'/r['candidate']/f'endpoint-{e}-reference/optimized.xyz';terms=energy_terms(xyz)-energy_terms(refxyz);assert abs(terms.sum()-r['mm_relative_kcal_mol'])<1e-5
        records.append(dict(candidate=r['candidate'],point=r['point'],qm_relative_kcal_mol=r['qm_relative_kcal_mol'],mm_relative_kcal_mol=r['mm_relative_kcal_mol'],uncorrected_error_kcal_mol=r['error_kcal_mol'],frozen_correction_kcal_mol=correction,corrected_error_kcal_mol=r['error_kcal_mol']+correction,mm_energy_term_differences=dict(zip(labels,terms.tolist())),optimized=source(xyz),reference_optimized=source(refxyz),system=source(sp)));del ctx,integ
    write(root/'assessment.json',dict(records=records,frozen_fit=source(frozen),mm_review=source(outer/'independent_review.json'),scope='Outer-angle holdout test with no refitting. Force-group decomposition is descriptive, not causal attribution or evidence for changing one term alone.',simulation_ready=False,minimum_certified=False));(root/'executed_source.py').write_text(Path(__file__).read_text())
    for p in sorted({r['point'] for r in records}):
        rr=[r for r in records if r['point']==p];print(p,'raw',[round(r['uncorrected_error_kcal_mol'],3) for r in rr],'corrected',[round(r['corrected_error_kcal_mol'],3) for r in rr])

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
