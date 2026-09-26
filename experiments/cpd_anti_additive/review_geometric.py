"""Independently inspect constrained QM output; never certify a minimum."""
import json,re,sys
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees


def review(root):
    plan=json.loads((root/'plan.json').read_text());tasks=plan.get('tasks',[dict(folder=str(root))]);out=[]
    for task in tasks:
        child=Path(task['folder']);p=json.loads((child/'plan.json').read_text());a=json.loads((child/'assessment.json').read_text());rows=json.loads((child/'progress.json').read_text())['evaluations']
        for row in rows:
            r=json.loads(checked(row['result']).read_text());x=np.load(checked(r['geometry']));assert screen(x,p)['passed'];native=checked(r['native']).read_text();res=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)];assert res and max(res)<=1e-10
        if a['native_optimizer_converged']:
            assert 'Converged!' in checked(a['log']).read_text();atoms,_=parse_xyz(checked(a['optimized']).read_text());assert [v[0] for v in atoms]==p['elements'];final=np.array([v[1:] for v in atoms])/BOHR;assert np.max(abs(final-x))<2e-8;assert screen(final,p)['passed']
        g=np.array(r['gradient']).ravel();n=np.zeros(x.size);idx=p['record']['torsion_indices'];h=1e-5
        for i in range(x.size):
            aa=x.copy().ravel();bb=aa.copy();aa[i]+=h;bb[i]-=h;n[i]=((_dihedral_degrees(*aa.reshape(-1,3)[idx])-_dihedral_degrees(*bb.reshape(-1,3)[idx])+180)%360-180)/(2*h)
        tg=g-n*(g@n)/(n@n) if p.get('freeze_torsion',True) else g;norm=np.linalg.norm(tg.reshape(-1,3),axis=1);mx=float(norm.max());rms=float(np.sqrt(np.mean(norm**2)))
        if a['native_optimizer_converged']:assert mx<1.5e-5 and rms<1e-5
        out.append(dict(point=child.name,converged=a['native_optimizer_converged'],evaluations=len(rows),reused=sum(v['reused'] for v in rows),last_energy_hartree=r['energy'],max_projected_atom_gradient=mx,rms_projected_atom_gradient=rms,assessment=source(child/'assessment.json')))
    write(root/'independent_review.json',dict(records=out,minimum_certified=False));print(json.dumps(out,indent=2))

if __name__=='__main__':review(Path(sys.argv[1]).resolve())
