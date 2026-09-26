"""Isolated charge-only conformer screening with bonded/LJ terms fixed."""
import json,sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.optimize import minimize
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees
ART=REPO/'.development-artifacts'

def run(root):
    root.mkdir(exist_ok=False);fit=ART/'cpd-anti-multiconformer-water-charge-v1/assessment.json';records=json.loads(fit.read_text())['records'];base=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text());baseline=base['candidates'][0];out=[];write(root/'plan.json',dict(charge_fit=source(fit),baseline=baseline,scope='Charge-only MM relaxation from original reference and a second conformation; fixed LJ/bonded parameters, no fitting or release'));(root/'executed_source.py').write_text(Path(__file__).read_text())
    for r in records:
        assert r['optimizer_success'] and r['max_constraint_error']<1e-8
        for e in (1,2):
            p=next(p for p in base['points'] if p['label']==f'endpoint-{e}-reference');ep=next(ep for ep in r['endpoints'] if ep['endpoint']==e);sp=checked(baseline['systems'][str(e)]);system=mm.XmlSerializer.deserialize(sp.read_text());nb=next(f for f in system.getForces() if isinstance(f,mm.NonbondedForce));q=np.array(ep['charges_e']);assert abs(q.sum())<1e-8;oldq=np.array([nb.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(len(q))]);names=json.loads(checked(p['record']['scan_plan']).read_text())['atom_map'];assert names==ep['atom_map']
            for i,n in enumerate(names):
                assert abs(q[i]-oldq[i]-r['charge_shifts_e'].get(n,0))<1e-8
                _,sig,eps=nb.getParticleParameters(i);nb.setParticleParameters(i,q[i],sig,eps)
            for k in range(nb.getNumExceptions()):
                i,j,prod,sig,eps=nb.getExceptionParameters(k);old=oldq[i]*oldq[j];new=q[i]*q[j];val=prod.value_in_unit(u.elementary_charge**2)
                if abs(old)<1e-15:assert abs(new)<1e-15
                replacement=val*new/old if abs(old)>1e-15 else val;nb.setExceptionParameters(k,i,j,replacement,sig,eps)
            parent=root/f"charge-{r['regularization']}"/f'endpoint-{e}';parent.mkdir(parents=True);(parent/'system.xml').write_text(mm.XmlSerializer.serialize(system))
            starts=[('original-qm',np.array(p['geometry_bohr'])*BOHR)]
            if e==1:starts.append(('original-mm',np.loadtxt(sp.parent/'minimum_A.txt')))
            else:
                a=json.loads((ART/'cpd-anti-remote-unconstrained-v1/endpoint-2-baseline-well/assessment.json').read_text());atoms,_=parse_xyz(checked(a['optimized']).read_text());starts.append(('remote-qm',np.array([v[1:] for v in atoms])))
            for label,x in starts:
                folder=parent/label;folder.mkdir();it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'))
                def evaluate(flat):
                    ctx.setPositions(np.asarray(flat).reshape(-1,3)*u.angstrom);s=ctx.getState(getEnergy=True,getForces=True);return s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),-np.array(s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()
                result=minimize(evaluate,x.ravel(),jac=True,method='L-BFGS-B',options=dict(maxiter=2000,gtol=1e-6,ftol=1e-14,maxls=40));final=result.x.reshape(-1,3);energy,g=evaluate(result.x);audit=screen(final/BOHR,dict(p,freeze_torsion=False));np.savetxt(folder/'final_A.txt',final);report=dict(regularization=r['regularization'],endpoint=e,start=label,energy_kcal_mol=energy,max_force=float(abs(g).max()),stationary=bool(abs(g).max()<.001),optimizer_success=bool(result.success),optimizer_message=str(result.message),geometry_audit=audit,torsion_deg=_dihedral_degrees(*final[p['record']['torsion_indices']]),system=source(parent/'system.xml'),final_geometry=source(folder/'final_A.txt'),minimum_certified=False);write(folder/'assessment.json',report);out.append(report);write(root/'progress.json',dict(records=out,total=12));del ctx,it
    write(root/'assessment.json',dict(records=out,simulation_ready=False,minimum_certified=False,scope='Independent force/geometry/Hessian audit still required; no parameter promotion'))

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
