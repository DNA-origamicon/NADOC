"""Isolated unconstrained geometry screening of preselected residual fits."""
import json,sys,math
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
import openmm as mm
from openmm import unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import _dihedral_degrees
ART=REPO/'.development-artifacts'

def run(root):
    root.mkdir(exist_ok=False);fitpath=ART/'cpd-anti-broad-torsion-diagnostic-v1/assessment.json';fits=[f for f in json.loads(fitpath.read_text())['fits'] if f['ridge']==.01];base=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text());records=[]
    write(root/'plan.json',dict(fits=fits,source=source(fitpath),scope='All candidates and torque families at preselected ridge .01; isolated MM systems, no CHARMM export or acceptance'))
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    for f in fits:
        e=f['endpoint'];c=next(c for c in base['candidates'] if c['label']==f['candidate']);p=next(p for p in base['points'] if p['label']==f'endpoint-{e}-reference');sp=checked(c['systems'][str(e)]);x=np.loadtxt(sp.parent/'minimum_A.txt');idx=p['record']['torsion_indices'];folder=root/f"{f['candidate']}-endpoint-{e}-{f['mode']}";folder.mkdir();system=mm.XmlSerializer.deserialize(sp.read_text())
        probe=mm.CustomTorsionForce('theta');probe.addTorsion(*idx,[]);probe.setForceGroup(31);system.addForce(probe);it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'));ctx.setPositions(x*u.angstrom);theta=ctx.getState(getEnergy=True,groups=1<<31).getPotentialEnergy().value_in_unit(u.kilojoule_per_mole);expected=math.radians(_dihedral_degrees(*x[idx]));sign=min((1,-1),key=lambda s:abs((s*theta-expected+math.pi)%(2*math.pi)-math.pi));assert abs((sign*theta-expected+math.pi)%(2*math.pi)-math.pi)<1e-7;del ctx,it;system.removeForce(system.getNumForces()-1)
        force=mm.CustomTorsionForce('a*(cos(d)-1)+b*(cos(2*d)-1)+c*sin(d)+q*sin(2*d);d=s*theta-r')
        for name in ('a','b','c','q','s','r'):force.addPerTorsionParameter(name)
        force.addTorsion(*idx,[v*4.184 for v in f['coefficients']]+[sign,math.radians(p['record']['target_degrees'])]);system.addForce(force);(folder/'system.xml').write_text(mm.XmlSerializer.serialize(system));it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'))
        def evaluate(flat):
            ctx.setPositions(np.asarray(flat).reshape(-1,3)*u.angstrom);st=ctx.getState(getEnergy=True,getForces=True);return st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),-np.asarray(st.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()
        energy,g=evaluate(x.ravel());i=int(np.argmax(abs(g)));aa=x.ravel().copy();bb=aa.copy();aa[i]+=1e-5;bb[i]-=1e-5;fd=(evaluate(aa)[0]-evaluate(bb)[0])/2e-5;assert abs(fd-g[i])<max(1e-5,abs(g[i])*1e-4)
        result=minimize(evaluate,x.ravel(),jac=True,method='L-BFGS-B',options=dict(maxiter=2000,gtol=1e-6,ftol=1e-14,maxls=40));final=result.x.reshape(-1,3);ef,gf=evaluate(result.x);angle=_dihedral_degrees(*final[idx]);audit=screen(final/BOHR,dict(p,record=dict(p['record'],target_degrees=angle)))
        heavy=np.array([el!='H' for el in p['elements']])
        def rms(a,b):
            a=a[heavy]-a[heavy].mean(axis=0);b=b[heavy]-b[heavy].mean(axis=0);uu,ss,vv=np.linalg.svd(a.T@b);rot=uu@np.diag([1,1,np.linalg.det(uu@vv)])@vv;return float(np.sqrt(np.mean(np.sum((a@rot-b)**2,axis=1))))
        qm=np.array(p['geometry_bohr'])*BOHR;np.savetxt(folder/'final_A.txt',final);r=dict(candidate=f['candidate'],endpoint=e,mode=f['mode'],optimizer_success=bool(result.success),optimizer_message=str(result.message),iterations=int(result.nit),max_force_kcal_mol_A=float(abs(gf).max()),stationary=bool(abs(gf).max()<.001),geometry_audit=audit,heavy_rms_shift_A=rms(final,x),heavy_rms_to_qm_before_A=rms(x,qm),heavy_rms_to_qm_after_A=rms(final,qm),torsion_shift_deg=float((angle-_dihedral_degrees(*x[idx])+180)%360-180),energy_change_kcal_mol=ef-energy,force_fd_error=abs(fd-g[i]),minimum_certified=False,simulation_ready=False,source_system=source(sp),candidate_system=source(folder/'system.xml'));write(folder/'assessment.json',r);records.append(r);write(root/'progress.json',dict(records=records,total=len(fits)));del ctx,it
    write(root/'assessment.json',dict(records=records,minimum_certified=False,simulation_ready=False,scope='Unconstrained MM geometry screening only; no Hessian, export, DNA or charge acceptance'))

if __name__=='__main__':run(Path(sys.argv[1]).resolve())
