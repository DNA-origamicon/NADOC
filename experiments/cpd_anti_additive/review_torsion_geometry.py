"""Independent trial-system forces, local MM Hessians and training geometry audit."""
import json,sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import app,unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz
ART=REPO/'.development-artifacts'

def review(root):
    rows=json.loads((root/'assessment.json').read_text())['records'];out=[]
    for r in rows:
        folder=checked(r['candidate_system']).parent;x=np.loadtxt(folder/'final_A.txt');system=mm.XmlSerializer.deserialize(checked(r['candidate_system']).read_text());base=checked(r['source_system']).parent;training=json.loads((base/'assessment.json').read_text());target=checked(training['sources'][0]);atoms,_=parse_xyz(target.read_text());qm=np.array([a[1:] for a in atoms]);psf=app.CharmmPsfFile(str(base/'fragment.psf'));it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'))
        def grad(z):
            ctx.setPositions(z*u.angstrom);st=ctx.getState(getForces=True);return -np.array(st.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()
        g=grad(x);assert abs(g).max()<.001;assert abs(abs(g).max()-r['max_force_kcal_mol_A'])<1e-8
        centered=x-x.mean(axis=0);rigid=np.column_stack([np.tile(v,(len(x),1)).ravel() for v in np.eye(3)]+[np.cross(np.tile(v,(len(x),1)),centered).ravel() for v in np.eye(3)]);basis=np.linalg.svd(rigid,full_matrices=True)[0][:,6:];curv=[]
        for h in (1e-4,5e-5):
            H=np.empty((x.size,x.size))
            for i in range(x.size):
                a=x.copy().ravel();b=a.copy();a[i]+=h;b[i]-=h;H[:,i]=(grad(a.reshape(-1,3))-grad(b.reshape(-1,3)))/(2*h)
            eig=np.linalg.eigvalsh(basis.T@((H+H.T)/2)@basis);curv.append(dict(step_A=h,minimum_internal_curvature=float(eig[0]),negative_modes=int((eig<0).sum())))
        def angle(z,ids):
            a,b,c=z[ids];v=a-b;w=c-b;return np.degrees(np.arccos(np.clip(v@w/np.linalg.norm(v)/np.linalg.norm(w),-1,1)))
        angles=[[a.atom1.idx,a.atom2.idx,a.atom3.idx] for a in psf.angle_list];bonds=[[b.atom1.idx,b.atom2.idx] for b in psf.bond_list];maxangle=max(abs(angle(x,i)-angle(qm,i)) for i in angles);maxbond=max(abs(np.linalg.norm(x[i]-x[j])-np.linalg.norm(qm[i]-qm[j])) for i,j in bonds)
        out.append(dict(candidate=r['candidate'],endpoint=r['endpoint'],mode=r['mode'],max_force=float(abs(g).max()),curvatures=curv,positive_local_mm_curvature=all(v['minimum_internal_curvature']>0 for v in curv),max_training_angle_error_deg=float(maxangle),max_training_bond_error_A=float(maxbond),final_geometry=source(folder/'final_A.txt'),training_target=source(target),candidate_system=r['candidate_system']));del ctx,it
    write(root/'independent_review.json',dict(records=out,scope='Independent local MM finite-difference Hessian checks at two step sizes and geometry against original fitting targets. No QM minimum, global minimum, transferability or simulation-release certification.',simulation_ready=False));print(json.dumps([{k:v for k,v in r.items() if k not in ('candidate_system','final_geometry','training_target')} for r in out],indent=2))

if __name__=='__main__':review(Path(sys.argv[1]).resolve())
