"""Independent constrained stationarity audit of saved MM optimizations."""
import json,sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees


def review(root):
    plan=json.loads((root/'plan.json').read_text());tasks=plan.get('tasks') or [dict(candidate=c,point=p) for c in plan['candidates'] for p in plan['points']];records=[]
    for task in tasks:
        c,p=task['candidate'],task['point'];folder=root/c['label']/p['label'];a=json.loads((folder/'assessment.json').read_text());assert a['converged'];checked(a['system']);checked(a['qm_source']);assert 'Converged!' in (folder/'geometric.log').read_text()
        atoms,_=parse_xyz((folder/'optimized.xyz').read_text());assert [a[0] for a in atoms]==p['elements'];x=np.array([a[1:] for a in atoms])/BOHR;assert screen(x,p)['passed']
        system=mm.XmlSerializer.deserialize(checked(a['system']).read_text());it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'));ctx.setPositions(x*BOHR*u.angstrom);st=ctx.getState(getEnergy=True,getForces=True)
        energy=st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole);g=-np.asarray(st.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()*BOHR/627.5094740631;assert abs(energy-a['energy_kcal_mol'])<1e-5
        n=np.zeros(x.size);idx=p['record']['torsion_indices'];h=1e-5
        for i in range(x.size):
            aa=x.copy().ravel();bb=aa.copy();aa[i]+=h;bb[i]-=h;ap=_dihedral_degrees(*aa.reshape(-1,3)[idx]);am=_dihedral_degrees(*bb.reshape(-1,3)[idx]);n[i]=((ap-am+180)%360-180)/(2*h)
        tg=g-n*(g@n)/(n@n);norm=np.linalg.norm(tg.reshape(-1,3),axis=1);mx=float(norm.max());rms=float(np.sqrt(np.mean(norm**2)));assert mx<5.1e-7 and rms<2.1e-7
        records.append(dict(candidate=c['label'],point=p['label'],max_projected_atom_force=mx,rms_projected_atom_force=rms,optimized=source(folder/'optimized.xyz'),native_log=source(folder/'geometric.log'),assessment=source(folder/'assessment.json')));del ctx,it
    write(root/'independent_review.json',dict(records=records,minimum_certified=False,verified_constrained_cases=len(records)))

if __name__=='__main__':review(Path(sys.argv[1]).resolve())
